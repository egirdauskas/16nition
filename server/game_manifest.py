"""Edit the user's own binary AndroidManifest.xml for the local game copy.

This applies the same project-authored edits that scripts/build_ignition_game.py
makes through apktool, but directly on the compiled manifest, so the launcher
never ships manifest bytes derived from the original. The result is
semantically identical to the apktool build (same `aapt2 dump xmltree` apart
from source line numbers); the lab certifies its exact hash.

Only the binary XML features used by Android manifests are supported. Parsing
an unmodified manifest and serializing it again reproduces the input bytes:
original nodes keep their string indexes, and only edited or added values are
interned (appended, or for new resource attributes inserted into the mapped
prefix, which shifts later indexes).
"""
import struct

XML = 0x0003
STRING_POOL = 0x0001
RESOURCE_MAP = 0x0180
START_NAMESPACE = 0x0100
END_NAMESPACE = 0x0101
START_ELEMENT = 0x0102
END_ELEMENT = 0x0103
NO_INDEX = 0xFFFFFFFF
UTF8 = 0x100

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12
TRUE = 0xFFFFFFFF

ANDROID = 'http://schemas.android.com/apk/res/android'
ATTRIBUTES = {
    'theme': 0x01010000,
    'name': 0x01010003,
    'permission': 0x01010006,
    'exported': 0x01010010,
    'value': 0x01010024,
    'minSdkVersion': 0x0101020C,
    'versionCode': 0x0101021B,
    'versionName': 0x0101021C,
    'targetSdkVersion': 0x01010270,
    'extractNativeLibs': 0x010104EA,
}
THEME_BLACK_NO_TITLE_FULLSCREEN = 0x0103000A


class Text(str):
    """A new string value; plain ints are indexes into the original pool."""


class Attribute:
    def __init__(self, namespace, name, raw, kind, data):
        self.namespace = namespace
        self.name = name
        self.raw = raw
        self.kind = kind
        self.data = data


class Element:
    def __init__(self, namespace, name, line, comment):
        self.namespace = namespace
        self.name = name
        self.line = line
        self.comment = comment
        self.end_line = line
        self.end_comment = NO_INDEX
        self.attributes = []
        self.children = []
        self.indexes = (0, 0, 0)


class Namespace:
    def __init__(self, prefix, uri, line, comment):
        self.prefix = prefix
        self.uri = uri
        self.line = line
        self.comment = comment
        self.end_line = line
        self.end_comment = NO_INDEX


class Manifest:
    def __init__(self, strings, resources, utf8, namespaces, root):
        self.strings = strings
        self.resources = resources
        self.utf8 = utf8
        self.namespaces = namespaces
        self.root = root

    def text(self, reference):
        if isinstance(reference, Text) or reference is None:
            return reference
        if reference == NO_INDEX:
            return None
        return self.strings[reference]

    def children(self, element, name):
        return [child for child in element.children if self.text(child.name) == name]

    def attribute(self, element, name):
        for item in element.attributes:
            if self.text(item.namespace) == ANDROID and self.text(item.name) == name:
                return item
        return None

    def string(self, element, name):
        item = self.attribute(element, name)
        if item is None or item.kind != TYPE_STRING:
            return None
        return self.text(item.data)


def _chunk(raw, offset):
    if offset + 8 > len(raw):
        raise ValueError('Truncated manifest chunk')
    kind, header, size = struct.unpack_from('<HHI', raw, offset)
    if header < 8 or size < header or offset + size > len(raw):
        raise ValueError('Invalid manifest chunk')
    return kind, header, size


def _length16(raw, offset):
    value = struct.unpack_from('<H', raw, offset)[0]
    if value & 0x8000:
        low = struct.unpack_from('<H', raw, offset + 2)[0]
        return ((value & 0x7FFF) << 16) | low, offset + 4
    return value, offset + 2


def _length8(raw, offset):
    value = raw[offset]
    if value & 0x80:
        return ((value & 0x7F) << 8) | raw[offset + 1], offset + 2
    return value, offset + 1


def _parse_strings(raw, offset):
    _, _, size, count, styles, flags, start, _ = struct.unpack_from('<HHIIIIII', raw, offset)
    if styles or flags & ~UTF8:
        raise ValueError('Unsupported manifest string pool')
    values = []
    for index in range(count):
        position = offset + start + struct.unpack_from('<I', raw, offset + 28 + 4 * index)[0]
        if flags & UTF8:
            _, position = _length8(raw, position)
            length, position = _length8(raw, position)
            values.append(raw[position:position + length].decode('utf-8'))
        else:
            length, position = _length16(raw, position)
            values.append(raw[position:position + 2 * length].decode('utf-16-le'))
    return values, bool(flags & UTF8)


def _index(strings, value):
    if value != NO_INDEX and value >= len(strings):
        raise ValueError('Manifest string index out of range')
    return value


def parse(raw):
    kind, header, size = _chunk(raw, 0)
    if kind != XML or header != 8 or size != len(raw):
        raise ValueError('Not a binary Android manifest')
    offset = 8
    kind, header, size = _chunk(raw, offset)
    if kind != STRING_POOL or header != 28:
        raise ValueError('Manifest string pool missing')
    strings, utf8 = _parse_strings(raw, offset)
    offset += size
    resources = []
    kind, header, size = _chunk(raw, offset)
    if kind == RESOURCE_MAP:
        resources = list(struct.unpack_from('<%dI' % ((size - 8) // 4), raw, offset + 8))
        offset += size
    namespaces = []
    open_namespaces = []
    stack = []
    root = None
    while offset < len(raw):
        kind, header, size = _chunk(raw, offset)
        if header != 16:
            raise ValueError('Unsupported manifest node header')
        line, comment = struct.unpack_from('<II', raw, offset + 8)
        comment = _index(strings, comment)
        body = offset + 16
        if kind == START_NAMESPACE:
            prefix, uri = (_index(strings, v) for v in struct.unpack_from('<II', raw, body))
            item = Namespace(prefix, uri, line, comment)
            namespaces.append(item)
            open_namespaces.append(item)
        elif kind == END_NAMESPACE:
            prefix, uri = struct.unpack_from('<II', raw, body)
            item = open_namespaces.pop()
            if (item.prefix, item.uri) != (prefix, uri):
                raise ValueError('Unbalanced manifest namespace')
            item.end_line = line
            item.end_comment = comment
        elif kind == START_ELEMENT:
            namespace, name, start, step, count, index_id, index_class, index_style = \
                struct.unpack_from('<IIHHHHHH', raw, body)
            if start != 20 or step != 20 or size != 16 + 20 + 20 * count:
                raise ValueError('Unsupported manifest attribute layout')
            element = Element(_index(strings, namespace), _index(strings, name), line, comment)
            element.indexes = (index_id, index_class, index_style)
            for position in range(body + 20, body + 20 + 20 * count, 20):
                values = struct.unpack_from('<IIIHBBI', raw, position)
                attribute_namespace, attribute_name, attribute_raw, value_size, zero, value_kind, data = values
                if value_size != 8 or zero:
                    raise ValueError('Unsupported manifest attribute value')
                if value_kind == TYPE_STRING:
                    data = _index(strings, data)
                element.attributes.append(Attribute(
                    _index(strings, attribute_namespace), _index(strings, attribute_name),
                    _index(strings, attribute_raw), value_kind, data))
            if stack:
                stack[-1].children.append(element)
            elif root is None:
                root = element
            else:
                raise ValueError('Manifest has several root elements')
            stack.append(element)
        elif kind == END_ELEMENT:
            namespace, name = struct.unpack_from('<II', raw, body)
            element = stack.pop()
            if (element.namespace, element.name) != (namespace, name):
                raise ValueError('Unbalanced manifest element')
            element.end_line = line
            element.end_comment = comment
        else:
            raise ValueError('Unsupported manifest node')
        offset += size
    if stack or open_namespaces or root is None:
        raise ValueError('Incomplete manifest')
    return Manifest(strings, resources, utf8, namespaces, root)


class _Pool:
    def __init__(self, manifest):
        self.mapped_count = len(manifest.resources)
        self.strings = list(manifest.strings)
        self.resources = list(manifest.resources)
        self.inserted = 0

    def original(self, index):
        if index == NO_INDEX or index < self.mapped_count:
            return index
        return index + self.inserted

    def add_attribute(self, name):
        resource = ATTRIBUTES[name]
        for index, value in enumerate(self.resources):
            if value == resource and self.strings[index] == name:
                return
        self.strings.insert(len(self.resources), name)
        self.resources.append(resource)
        self.inserted += 1

    def add(self, value):
        if value not in self.strings[len(self.resources):]:
            self.strings.append(value)

    def reference(self, value):
        if value is None:
            return NO_INDEX
        if isinstance(value, Text):
            return len(self.resources) + self.strings[len(self.resources):].index(value)
        return self.original(value)

    def attribute_name(self, value):
        if isinstance(value, Text) and value in ATTRIBUTES:
            resource = ATTRIBUTES[value]
            for index, item in enumerate(self.resources):
                if item == resource and self.strings[index] == value:
                    return index
        return self.reference(value)


def _walk(element):
    yield element
    for child in element.children:
        yield from _walk(child)


def _intern(manifest, pool):
    # New resource attribute names first: inserting them shifts later indexes.
    for element in _walk(manifest.root):
        for item in element.attributes:
            if isinstance(item.name, Text) and item.name in ATTRIBUTES:
                pool.add_attribute(item.name)
    for element in _walk(manifest.root):
        references = [element.namespace, element.name, element.comment, element.end_comment]
        for item in element.attributes:
            references += [item.namespace, item.raw]
            if item.kind == TYPE_STRING:
                references.append(item.data)
            if not (isinstance(item.name, Text) and item.name in ATTRIBUTES):
                references.append(item.name)
        for value in references:
            if isinstance(value, Text):
                pool.add(value)


def _encode_strings(strings, utf8):
    data = bytearray()
    offsets = []
    for value in strings:
        offsets.append(len(data))
        if utf8:
            encoded = value.encode('utf-8')
            for length in (len(value.encode('utf-16-le')) // 2, len(encoded)):
                if length > 0x7F:
                    data += bytes([0x80 | (length >> 8), length & 0xFF])
                else:
                    data.append(length)
            data += encoded + b'\0'
        else:
            encoded = value.encode('utf-16-le')
            length = len(encoded) // 2
            if length > 0x7FFF:
                data += struct.pack('<HH', 0x8000 | (length >> 16), length & 0xFFFF)
            else:
                data += struct.pack('<H', length)
            data += encoded + b'\0\0'
    data += b'\0' * (-len(data) % 4)
    start = 28 + 4 * len(strings)
    header = struct.pack('<HHIIIIII', STRING_POOL, 28, start + len(data), len(strings), 0,
                         UTF8 if utf8 else 0, start, 0)
    return header + struct.pack('<%dI' % len(strings), *offsets) + bytes(data)


def _node(kind, line, comment, body):
    return struct.pack('<HHIII', kind, 16, 16 + len(body), line, comment) + body


def serialize(manifest):
    pool = _Pool(manifest)
    _intern(manifest, pool)
    ref = pool.reference
    nodes = bytearray()
    for namespace in manifest.namespaces:
        nodes += _node(START_NAMESPACE, namespace.line, ref(namespace.comment),
                       struct.pack('<II', ref(namespace.prefix), ref(namespace.uri)))

    def element_nodes(element):
        out = bytearray()
        body = struct.pack('<IIHHHHHH', ref(element.namespace), ref(element.name),
                           20, 20, len(element.attributes), *element.indexes)
        for item in element.attributes:
            data = ref(item.data) if item.kind == TYPE_STRING else item.data
            body += struct.pack('<IIIHBBI', ref(item.namespace), pool.attribute_name(item.name),
                                ref(item.raw), 8, 0, item.kind, data)
        out += _node(START_ELEMENT, element.line, ref(element.comment), body)
        for child in element.children:
            out += element_nodes(child)
        out += _node(END_ELEMENT, element.end_line, ref(element.end_comment),
                     struct.pack('<II', ref(element.namespace), ref(element.name)))
        return out

    nodes += element_nodes(manifest.root)
    for namespace in reversed(manifest.namespaces):
        nodes += _node(END_NAMESPACE, namespace.end_line, ref(namespace.end_comment),
                       struct.pack('<II', ref(namespace.prefix), ref(namespace.uri)))
    body = _encode_strings(pool.strings, manifest.utf8)
    if pool.resources:
        body += struct.pack('<HHI', RESOURCE_MAP, 8, 8 + 4 * len(pool.resources))
        body += struct.pack('<%dI' % len(pool.resources), *pool.resources)
    body += nodes
    return struct.pack('<HHI', XML, 8, 8 + len(body)) + body


def _android(manifest):
    for namespace in manifest.namespaces:
        if manifest.text(namespace.uri) == ANDROID:
            return namespace.uri
    raise ValueError('Manifest lacks the Android namespace')


def _set(manifest, element, name, kind, data):
    if element.indexes != (0, 0, 0):
        raise ValueError('Unsupported manifest element indexes')
    if kind == TYPE_STRING:
        data = Text(data)
    item = manifest.attribute(element, name)
    if item is None:
        item = Attribute(_android(manifest), Text(name), None, kind, data)
        element.attributes.append(item)
    item.kind = kind
    item.data = data
    item.raw = data if kind == TYPE_STRING else None
    # aapt orders resource attributes by ID; keep that order.
    element.attributes.sort(key=lambda value: _resource(manifest, value))


def _resource(manifest, attribute):
    if isinstance(attribute.name, Text):
        return ATTRIBUTES.get(attribute.name, NO_INDEX)
    if attribute.name < len(manifest.resources):
        return manifest.resources[attribute.name]
    return NO_INDEX


def _child(manifest, parent, name, attributes):
    element = Element(None, Text(name), parent.end_line, None)
    element.end_comment = None
    for attribute_name, kind, data in attributes:
        _set(manifest, element, attribute_name, kind, data)
    parent.children.append(element)
    return element


def _integer(manifest, element, name, *, lowest, highest):
    item = manifest.attribute(element, name)
    if item is None or item.kind != TYPE_INT_DEC or not lowest <= item.data <= highest:
        raise ValueError('Original manifest metadata mismatch')


def edit(raw, *, original_version_code, original_version_name, version_code, version_name):
    """Return the local game manifest; mirrors build_ignition_game.py edits."""
    manifest = parse(raw)
    root = manifest.root
    if manifest.text(root.name) != 'manifest':
        raise ValueError('Not an application manifest')
    code = manifest.attribute(root, 'versionCode')
    if (code is None or code.kind != TYPE_INT_DEC or code.data != original_version_code
            or manifest.string(root, 'versionName') != original_version_name):
        raise ValueError('Original manifest version differs')
    _set(manifest, root, 'versionCode', TYPE_INT_DEC, version_code)
    _set(manifest, root, 'versionName', TYPE_STRING, version_name)
    sdk = manifest.children(root, 'uses-sdk')
    if len(sdk) != 1:
        raise ValueError('Original manifest metadata mismatch')
    _integer(manifest, sdk[0], 'minSdkVersion', lowest=19, highest=19)
    _integer(manifest, sdk[0], 'targetSdkVersion', lowest=19, highest=24)
    _set(manifest, sdk[0], 'minSdkVersion', TYPE_INT_DEC, 24)
    _set(manifest, sdk[0], 'targetSdkVersion', TYPE_INT_DEC, 24)
    applications = manifest.children(root, 'application')
    if len(applications) != 1:
        raise ValueError('Original application missing')
    application = applications[0]
    if manifest.attribute(application, 'name') is not None:
        raise ValueError('Original application class changed')
    _set(manifest, application, 'name', TYPE_STRING, 'org.ignition.game.GameApplication')
    _set(manifest, application, 'extractNativeLibs', TYPE_INT_BOOLEAN, TRUE)
    removed = 0
    for activity in manifest.children(application, 'activity'):
        if manifest.string(activity, 'name') != 'com.ea.gp.fifaworld.fifa':
            continue
        kept = []
        for child in activity.children:
            launcher = (manifest.text(child.name) == 'intent-filter' and any(
                manifest.string(action, 'name') == 'android.intent.action.MAIN'
                for action in manifest.children(child, 'action')))
            if launcher:
                removed += 1
            else:
                kept.append(child)
        activity.children = kept
    if removed != 1:
        raise ValueError('Original launcher activity differs')
    bootstrap = _child(manifest, application, 'activity', [
        ('name', TYPE_STRING, 'org.ignition.game.BootstrapActivity'),
        ('exported', TYPE_INT_BOOLEAN, TRUE),
        ('theme', TYPE_REFERENCE, THEME_BLACK_NO_TITLE_FULLSCREEN),
    ])
    intent = _child(manifest, bootstrap, 'intent-filter', [])
    _child(manifest, intent, 'action', [('name', TYPE_STRING, 'android.intent.action.MAIN')])
    _child(manifest, intent, 'category', [('name', TYPE_STRING, 'android.intent.category.LAUNCHER')])
    _child(manifest, application, 'service', [
        ('name', TYPE_STRING, 'org.ignition.game.GameControlService'),
        ('exported', TYPE_INT_BOOLEAN, TRUE),
        ('permission', TYPE_STRING, 'org.ignition.launcher.permission.GAME_ASSETS'),
    ])
    _child(manifest, application, 'meta-data', [
        ('name', TYPE_STRING, 'org.ignition.route.version'),
        ('value', TYPE_INT_DEC, 1),
    ])
    _child(manifest, root, 'uses-permission', [
        ('name', TYPE_STRING, 'org.ignition.launcher.permission.GAME_ASSETS'),
    ])
    return serialize(manifest)

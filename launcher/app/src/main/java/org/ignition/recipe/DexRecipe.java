package org.ignition.recipe;

import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.ReferenceType;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.ClassDef;
import com.android.tools.smali.dexlib2.iface.Field;
import com.android.tools.smali.dexlib2.iface.Method;
import com.android.tools.smali.dexlib2.iface.MethodImplementation;
import com.android.tools.smali.dexlib2.iface.MethodParameter;
import com.android.tools.smali.dexlib2.iface.instruction.Instruction;
import com.android.tools.smali.dexlib2.iface.instruction.OneRegisterInstruction;
import com.android.tools.smali.dexlib2.iface.instruction.ReferenceInstruction;
import com.android.tools.smali.dexlib2.iface.reference.StringReference;
import com.android.tools.smali.dexlib2.iface.value.EncodedValue;
import com.android.tools.smali.dexlib2.iface.value.StringEncodedValue;
import com.android.tools.smali.dexlib2.immutable.ImmutableClassDef;
import com.android.tools.smali.dexlib2.immutable.ImmutableField;
import com.android.tools.smali.dexlib2.immutable.ImmutableMethod;
import com.android.tools.smali.dexlib2.immutable.ImmutableMethodImplementation;
import com.android.tools.smali.dexlib2.immutable.ImmutableMethodParameter;
import com.android.tools.smali.dexlib2.immutable.instruction.ImmutableInstruction21c;
import com.android.tools.smali.dexlib2.immutable.instruction.ImmutableInstruction31c;
import com.android.tools.smali.dexlib2.immutable.reference.ImmutableStringReference;
import com.android.tools.smali.dexlib2.immutable.value.ImmutableStringEncodedValue;
import com.android.tools.smali.dexlib2.writer.io.MemoryDataStore;
import com.android.tools.smali.dexlib2.writer.pool.DexPool;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Rebuild the user's own game classes.dex from a plan of project-authored edits.
 *
 * <p>Nothing from the original game is bundled: routed strings are matched by
 * SHA-256, replacement method bodies come from a project-assembled holder DEX
 * and the added classes come from the project shim DEX. The caller verifies the
 * input and output hashes. This class has no Android dependencies so the lab
 * runs the identical code to certify those hashes.
 *
 * <p>Plan lines (UTF-8, one directive per line, fields separated by one space):
 * <pre>
 * api 24
 * route &lt;class&gt; &lt;sha256 of old string&gt; &lt;count&gt; &lt;new string&gt;
 * method &lt;class&gt; &lt;holder class&gt; &lt;name&gt; &lt;prototype&gt;
 * </pre>
 */
public final class DexRecipe {
    private DexRecipe() {}

    private static final class Route {
        final String digest;
        final int expected;
        final String replacement;
        int found;

        Route(String digest, int expected, String replacement) {
            this.digest = digest;
            this.expected = expected;
            this.replacement = replacement;
        }
    }

    private static final class Replacement {
        final String holder;
        final String name;
        final String prototype;
        boolean applied;

        Replacement(String holder, String name, String prototype) {
            this.holder = holder;
            this.name = name;
            this.prototype = prototype;
        }
    }

    public static byte[] apply(byte[] original, String plan, byte[] shim, byte[] holders)
            throws IOException {
        int api = -1;
        Map<String, List<Route>> routes = new LinkedHashMap<>();
        Map<String, List<Replacement>> replacements = new LinkedHashMap<>();
        for (String line : plan.split("\n")) {
            if (line.isEmpty()) {
                continue;
            }
            String[] part = line.split(" ", -1);
            if (part[0].equals("api") && part.length == 2 && api < 0) {
                api = Integer.parseInt(part[1]);
            } else if (part[0].equals("route") && part.length >= 5) {
                String replacement = line.substring(
                    part[0].length() + part[1].length() + part[2].length() + part[3].length() + 4);
                Route route = new Route(part[2], Integer.parseInt(part[3]), replacement);
                routes.computeIfAbsent(part[1], key -> new ArrayList<>()).add(route);
            } else if (part[0].equals("method") && part.length == 5) {
                Replacement item = new Replacement(part[2], part[3], part[4]);
                replacements.computeIfAbsent(part[1], key -> new ArrayList<>()).add(item);
            } else {
                throw new IOException("Invalid recipe plan line");
            }
        }
        if (api < 24) {
            throw new IOException("Recipe plan API level missing");
        }
        Opcodes opcodes = Opcodes.forApi(api);
        DexBackedDexFile source = new DexBackedDexFile(opcodes, original);
        Map<String, ClassDef> holderClasses = new HashMap<>();
        for (ClassDef item : new DexBackedDexFile(opcodes, holders).getClasses()) {
            holderClasses.put(item.getType(), item);
        }
        DexPool pool = new DexPool(opcodes);
        Set<String> written = new HashSet<>();
        for (ClassDef item : source.getClasses()) {
            ClassDef result = item;
            List<Route> classRoutes = routes.get(item.getType());
            List<Replacement> classMethods = replacements.get(item.getType());
            if (classRoutes != null || classMethods != null) {
                result = rewrite(item, classRoutes, classMethods, holderClasses);
            }
            written.add(item.getType());
            pool.internClass(result);
        }
        for (ClassDef item : new DexBackedDexFile(opcodes, shim).getClasses()) {
            if (!written.add(item.getType())) {
                throw new IOException("Shim class collides with original class");
            }
            pool.internClass(item);
        }
        for (Map.Entry<String, List<Route>> entry : routes.entrySet()) {
            for (Route route : entry.getValue()) {
                if (route.found != route.expected) {
                    throw new IOException("Routed constant count differs in " + entry.getKey());
                }
            }
        }
        for (Map.Entry<String, List<Replacement>> entry : replacements.entrySet()) {
            for (Replacement item : entry.getValue()) {
                if (!item.applied) {
                    throw new IOException("Replacement method not found in " + entry.getKey());
                }
            }
        }
        MemoryDataStore store = new MemoryDataStore();
        pool.writeTo(store);
        return Arrays.copyOf(store.getBuffer(), store.getSize());
    }

    private static ClassDef rewrite(ClassDef item, List<Route> routes,
                                    List<Replacement> replacements,
                                    Map<String, ClassDef> holders) throws IOException {
        List<Route> active = routes == null ? Collections.<Route>emptyList() : routes;
        List<Field> fields = new ArrayList<>();
        for (Field field : item.getFields()) {
            EncodedValue value = field.getInitialValue();
            if (value instanceof StringEncodedValue) {
                Route route = match(active, ((StringEncodedValue) value).getValue());
                if (route != null) {
                    value = new ImmutableStringEncodedValue(route.replacement);
                }
            }
            fields.add(new ImmutableField(field.getDefiningClass(), field.getName(), field.getType(),
                field.getAccessFlags(), value, field.getAnnotations(),
                field.getHiddenApiRestrictions()));
        }
        List<Method> methods = new ArrayList<>();
        for (Method method : item.getMethods()) {
            Replacement replacement = find(replacements, method);
            if (replacement != null) {
                methods.add(replace(method, replacement, holders));
            } else {
                methods.add(route(method, active));
            }
        }
        return new ImmutableClassDef(item.getType(), item.getAccessFlags(), item.getSuperclass(),
            item.getInterfaces(), item.getSourceFile(), item.getAnnotations(), fields, methods);
    }

    private static Method route(Method method, List<Route> routes) throws IOException {
        MethodImplementation implementation = method.getImplementation();
        if (implementation == null || routes.isEmpty()) {
            return method;
        }
        List<Instruction> instructions = new ArrayList<>();
        boolean changed = false;
        for (Instruction instruction : implementation.getInstructions()) {
            Instruction result = instruction;
            Opcode opcode = instruction.getOpcode();
            if (opcode == Opcode.CONST_STRING || opcode == Opcode.CONST_STRING_JUMBO) {
                ReferenceInstruction reference = (ReferenceInstruction) instruction;
                if (reference.getReferenceType() != ReferenceType.STRING) {
                    throw new IOException("Unexpected string instruction");
                }
                String value = ((StringReference) reference.getReference()).getString();
                Route route = match(routes, value);
                if (route != null) {
                    int register = ((OneRegisterInstruction) instruction).getRegisterA();
                    ImmutableStringReference text = new ImmutableStringReference(route.replacement);
                    if (opcode == Opcode.CONST_STRING) {
                        result = new ImmutableInstruction21c(opcode, register, text);
                    } else {
                        result = new ImmutableInstruction31c(opcode, register, text);
                    }
                    changed = true;
                }
            }
            instructions.add(result);
        }
        if (!changed) {
            return method;
        }
        MethodImplementation routed = new ImmutableMethodImplementation(
            implementation.getRegisterCount(), instructions, implementation.getTryBlocks(),
            implementation.getDebugItems());
        return new ImmutableMethod(method.getDefiningClass(), method.getName(),
            method.getParameters(), method.getReturnType(), method.getAccessFlags(),
            method.getAnnotations(), method.getHiddenApiRestrictions(), routed);
    }

    private static Method replace(Method method, Replacement replacement,
                                  Map<String, ClassDef> holders) throws IOException {
        ClassDef holder = holders.get(replacement.holder);
        if (holder == null) {
            throw new IOException("Replacement holder missing");
        }
        Method body = null;
        for (Method candidate : holder.getMethods()) {
            if (candidate.getName().equals(method.getName())
                    && prototype(candidate).equals(prototype(method))
                    && candidate.getAccessFlags() == method.getAccessFlags()) {
                body = candidate;
            }
        }
        if (body == null || body.getImplementation() == null || replacement.applied) {
            throw new IOException("Replacement body differs from original method shape");
        }
        replacement.applied = true;
        // Like a whole-method smali replacement: no parameter names or annotations remain.
        List<MethodParameter> parameters = new ArrayList<>();
        for (MethodParameter parameter : method.getParameters()) {
            parameters.add(new ImmutableMethodParameter(parameter.getType(), null, null));
        }
        return new ImmutableMethod(method.getDefiningClass(), method.getName(), parameters,
            method.getReturnType(), method.getAccessFlags(), null, null,
            ImmutableMethodImplementation.of(body.getImplementation()));
    }

    private static Replacement find(List<Replacement> replacements, Method method) {
        if (replacements == null) {
            return null;
        }
        for (Replacement item : replacements) {
            if (item.name.equals(method.getName()) && item.prototype.equals(prototype(method))) {
                return item;
            }
        }
        return null;
    }

    private static String prototype(Method method) {
        StringBuilder value = new StringBuilder("(");
        for (MethodParameter parameter : method.getParameters()) {
            value.append(parameter.getType());
        }
        return value.append(')').append(method.getReturnType()).toString();
    }

    private static Route match(List<Route> routes, String value) throws IOException {
        if (routes.isEmpty()) {
            return null;
        }
        String digest = sha256(value.getBytes(StandardCharsets.UTF_8));
        for (Route route : routes) {
            if (route.digest.equals(digest)) {
                route.found++;
                return route;
            }
        }
        return null;
    }

    static String sha256(byte[] raw) throws IOException {
        try {
            StringBuilder value = new StringBuilder();
            for (byte item : MessageDigest.getInstance("SHA-256").digest(raw)) {
                value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
            }
            return value.toString();
        } catch (java.security.NoSuchAlgorithmException error) {
            throw new IOException(error);
        }
    }

    private static byte[] read(String path) throws IOException {
        try (RandomAccessFile file = new RandomAccessFile(path, "r")) {
            byte[] raw = new byte[(int) file.length()];
            file.readFully(raw);
            return raw;
        }
    }

    /** Lab entry point: original.dex plan.txt shim.dex holders.dex output.dex */
    public static void main(String[] args) throws IOException {
        if (args.length != 5) {
            throw new IOException("usage: original.dex plan.txt shim.dex holders.dex output.dex");
        }
        String plan = new String(read(args[1]), StandardCharsets.UTF_8);
        byte[] result = apply(read(args[0]), plan, read(args[2]), read(args[3]));
        try (FileOutputStream output = new FileOutputStream(new File(args[4]))) {
            output.write(result);
        }
        System.out.println(sha256(result));
    }
}

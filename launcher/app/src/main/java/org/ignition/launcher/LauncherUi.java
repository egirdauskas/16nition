package org.ignition.launcher;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.text.TextUtils;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.TextView;
import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.Map;
import org.luaj.vm2.Globals;
import org.luaj.vm2.LuaTable;
import org.luaj.vm2.LuaValue;
import org.luaj.vm2.compiler.LuaC;
import org.luaj.vm2.lib.BaseLib;
import org.luaj.vm2.lib.MathLib;
import org.luaj.vm2.lib.StringLib;
import org.luaj.vm2.lib.TableLib;

/** Native Android controls arranged by project-owned Lua, independent of FIFA's engine. */
final class LauncherUi extends ViewGroup {
    private final LuaValue theme;
    private final float density;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Map<String, View> views = new LinkedHashMap<>();
    final TextView club;
    final TextView status;

    LauncherUi(Context context) throws Exception {
        super(context);
        density = getResources().getDisplayMetrics().density;
        Globals globals = new Globals();
        globals.load(new BaseLib());
        // Core libraries expect package.loaded; no file/network/Java libraries are exposed.
        LuaTable loaded = new LuaTable();
        LuaTable packages = new LuaTable();
        packages.set("loaded", loaded);
        globals.set("package", packages);
        globals.load(new TableLib());
        globals.load(new StringLib());
        globals.load(new MathLib());
        LuaC.install(globals);
        try (InputStream input = context.getAssets().open("ui/launcher.lua")) {
            theme = globals.load(input, "@ui/launcher.lua", "t", globals).call();
        }
        if (theme.get("version").checkint() != 1) throw new IllegalStateException("Unknown launcher layout");
        setWillNotDraw(false);
        setBackgroundColor(color("background"));
        setFocusable(false);

        ImageView logo = new ImageView(context);
        logo.setImageResource(R.drawable.brand_logo);
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        logo.setContentDescription("16NITION logo");
        add("logo", logo);
        add("brand", text(theme.get("brand").checkjstring(), 29, "ink"));
        add("context", text(theme.get("context").checkjstring(), 11, "muted"));

        LuaValue tiles = theme.get("tiles");
        for (int index = 1; index <= tiles.length(); index++) {
            LuaValue tile = tiles.get(index);
            add(tile.get("id").checkjstring(), new Tile(context, tile));
        }
        club = text("", 19, "ink");
        add("club", club);
        status = text("Stopped", 12, "muted");
        add("status", status);
    }

    private int color(String key) {
        return Color.parseColor(theme.get("colors").get(key).checkjstring());
    }

    private TextView text(String value, int size, String ink) {
        TextView view = new TextView(getContext());
        view.setText(value);
        view.setTextColor(color(ink));
        view.setTextSize(size);
        view.setTypeface(Typeface.create("sans-serif-condensed", Typeface.NORMAL));
        view.setSingleLine(true);
        view.setEllipsize(TextUtils.TruncateAt.END);
        view.setGravity(android.view.Gravity.CENTER_VERTICAL);
        view.setIncludeFontPadding(false);
        return view;
    }

    private void add(String id, View view) {
        view.setId(View.generateViewId());
        views.put(id, view);
        addView(view);
    }

    Button action(String id, Runnable action) {
        Button button = (Button) views.get(id);
        button.setOnClickListener(view -> action.run());
        return button;
    }

    private LuaValue frames(int width, int height) {
        return theme.get("layout").call(LuaValue.valueOf(width / density), LuaValue.valueOf(height / density));
    }

    @Override protected void onMeasure(int widthSpec, int heightSpec) {
        int width = MeasureSpec.getSize(widthSpec);
        int height = MeasureSpec.getSize(heightSpec);
        LuaValue layout = frames(width, height);
        for (Map.Entry<String, View> entry : views.entrySet()) {
            LuaValue rect = layout.get(entry.getKey());
            int w = Math.max(1, Math.round((float) rect.get(3).checkdouble() * density));
            int h = Math.max(1, Math.round((float) rect.get(4).checkdouble() * density));
            entry.getValue().measure(MeasureSpec.makeMeasureSpec(w, MeasureSpec.EXACTLY),
                MeasureSpec.makeMeasureSpec(h, MeasureSpec.EXACTLY));
        }
        setMeasuredDimension(width, height);
    }

    @Override protected void onLayout(boolean changed, int l, int t, int r, int b) {
        LuaValue layout = frames(r - l, b - t);
        for (Map.Entry<String, View> entry : views.entrySet()) {
            LuaValue rect = layout.get(entry.getKey());
            int x = Math.round((float) rect.get(1).checkdouble() * density);
            int y = Math.round((float) rect.get(2).checkdouble() * density);
            View view = entry.getValue();
            view.layout(x, y, x + view.getMeasuredWidth(), y + view.getMeasuredHeight());
        }
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float w = getWidth(), h = getHeight();
        paint.setShader(new LinearGradient(0, 0, w, h, Color.WHITE, color("background"), Shader.TileMode.CLAMP));
        canvas.drawRect(0, 0, w, h, paint);
        paint.setShader(null);
        paint.setColor(0x0D7398B0);
        Path facets = new Path();
        facets.moveTo(w * .53f, 0);
        facets.lineTo(w, 0);
        facets.lineTo(w, h * .68f);
        facets.close();
        canvas.drawPath(facets, paint);
        paint.setColor(color("blue"));
        canvas.drawRect(0, 0, w, 3 * density, paint);
        paint.setColor(color("line"));
        canvas.drawRect(0, h - 29 * density, w, h - 28 * density, paint);
    }

    private final class Tile extends Button {
        private final String kind;
        private final String title;
        private final String hint;
        private final Typeface font = Typeface.create("sans-serif-condensed", Typeface.NORMAL);
        private final Paint ink = new Paint(Paint.ANTI_ALIAS_FLAG);

        Tile(Context context, LuaValue value) {
            super(context);
            kind = value.get("icon").checkjstring();
            title = value.get("title").checkjstring();
            hint = value.get("hint").checkjstring();
            setText(value.get("label").checkjstring());
            setAllCaps(false);
            setBackgroundColor(Color.TRANSPARENT);
            setStateListAnimator(null);
            setElevation(0);
            setTranslationZ(0);
            setPadding(0, 0, 0, 0);
            setMinWidth(0);
            setMinimumWidth(0);
            setMinHeight(0);
            setMinimumHeight(0);
            setFocusable(true);
            setSoundEffectsEnabled(true);
        }

        @Override protected void drawableStateChanged() {
            super.drawableStateChanged();
            invalidate();
        }

        private void label(Canvas canvas, String text, float x, float y, float size, int color, float width) {
            ink.setTypeface(font);
            ink.setTextSize(size * getResources().getDisplayMetrics().scaledDensity);
            ink.setColor(color);
            if (ink.measureText(text) > width) ink.setTextSize(ink.getTextSize() * width / ink.measureText(text));
            canvas.drawText(text, x, y, ink);
        }

        @Override protected void onDraw(Canvas canvas) {
            float w = getWidth(), h = getHeight(), d = density;
            boolean selected = isPressed() || isFocused();
            boolean hero = kind.equals("pitch");
            boolean compact = kind.equals("points");
            int blue = color(selected ? "blue_dark" : "blue");
            ink.setShader(new LinearGradient(0, 0, w, h, color("white"),
                Color.parseColor(hero ? "#D1E1EB" : "#E1EAF0"), Shader.TileMode.CLAMP));
            canvas.drawRect(0, 0, w, h, ink);
            ink.setShader(null);
            if (hero) {
                pitch(canvas, w, h, d);
                ink.setColor(blue);
                canvas.drawRect(0, h - 42 * d, w, h, ink);
                label(canvas, title, 16 * d, 31 * d, 23, color("ink"), w - 32 * d);
                label(canvas, hint, 16 * d, h - 14 * d, 19, color("white"), w - 50 * d);
                arrow(canvas, w - 25 * d, h - 21 * d, 9 * d, color("white"), false);
            } else if (compact) {
                ink.setColor(selected ? blue : color("ink"));
                canvas.drawRect(0, 0, w, h, ink);
                label(canvas, title, 14 * d, h / 2 + 6 * d, 18, color("white"), w * .5f - 20 * d);
                ink.setTypeface(font);
                ink.setTextSize(14 * getResources().getDisplayMetrics().scaledDensity);
                float labelWidth = ink.measureText(hint);
                label(canvas, hint, w - labelWidth - 14 * d, h / 2 + 5 * d, 14, color("white"), w * .5f - 20 * d);
            } else {
                label(canvas, title, 12 * d, 26 * d, 19, color("ink"), w - 24 * d);
                label(canvas, hint, 12 * d, h - 12 * d, 10, color("muted"), w - 40 * d);
                symbol(canvas, w - 26 * d, h / 2 + 5 * d, 12 * d, blue);
            }
            ink.setColor(selected ? blue : color("line"));
            ink.setStyle(Paint.Style.STROKE);
            ink.setStrokeWidth(selected ? 3 * d : d);
            canvas.drawRect(1, 1, w - 1, h - 1, ink);
            ink.setStyle(Paint.Style.FILL);
            if (!isEnabled()) {
                ink.setColor(0x99E8EFF3);
                canvas.drawRect(0, 0, w, h, ink);
            }
        }

        private void pitch(Canvas canvas, float w, float h, float d) {
            canvas.save();
            canvas.clipRect(0, 76 * d, w, h - 42 * d);
            ink.setColor(0x528BA9BB);
            ink.setStyle(Paint.Style.STROKE);
            ink.setStrokeWidth(d);
            RectF field = new RectF(w * .13f, h * .40f, w * 1.04f, h * 1.02f);
            canvas.drawRect(field, ink);
            canvas.drawLine(field.centerX(), field.top, field.centerX(), field.bottom, ink);
            canvas.drawOval(field.centerX() - w * .11f, field.centerY() - h * .12f,
                field.centerX() + w * .11f, field.centerY() + h * .12f, ink);
            canvas.drawRect(field.left, field.centerY() - h * .18f,
                field.left + w * .17f, field.centerY() + h * .18f, ink);
            ink.setStyle(Paint.Style.FILL);
            canvas.restore();
        }

        private void arrow(Canvas canvas, float x, float y, float radius, int color, boolean up) {
            ink.setColor(color);
            ink.setStyle(Paint.Style.STROKE);
            ink.setStrokeWidth(1.5f * density);
            Path path = new Path();
            if (up) {
                path.moveTo(x - radius * .6f, y);
                path.lineTo(x, y - radius * .6f);
                path.lineTo(x + radius * .6f, y);
                path.moveTo(x, y - radius * .6f);
                path.lineTo(x, y + radius);
            } else {
                path.moveTo(x - radius * .35f, y - radius * .7f);
                path.lineTo(x + radius * .35f, y);
                path.lineTo(x - radius * .35f, y + radius * .7f);
            }
            canvas.drawPath(path, ink);
            ink.setStyle(Paint.Style.FILL);
        }

        private void symbol(Canvas canvas, float x, float y, float r, int color) {
            ink.setColor(color);
            ink.setStyle(Paint.Style.STROKE);
            ink.setStrokeWidth(1.5f * density);
            if (kind.equals("clubs")) {
                Path shield = new Path();
                shield.moveTo(x - r, y - r);
                shield.lineTo(x + r, y - r);
                shield.lineTo(x + r * .8f, y + r * .5f);
                shield.lineTo(x, y + r);
                shield.lineTo(x - r * .8f, y + r * .5f);
                shield.close();
                canvas.drawPath(shield, ink);
            } else if (kind.equals("setup")) {
                for (int n = -1; n <= 1; n++) {
                    float yy = y + n * r * .65f;
                    canvas.drawLine(x - r, yy, x + r, yy, ink);
                    canvas.drawCircle(x + (n == 0 ? r * .4f : -r * .4f), yy, 2 * density, ink);
                }
            } else {
                canvas.drawLine(x - r, y + r * .5f, x - r, y + r, ink);
                canvas.drawLine(x - r, y + r, x + r, y + r, ink);
                canvas.drawLine(x + r, y + r, x + r, y + r * .5f, ink);
                canvas.save();
                if (kind.equals("import")) canvas.rotate(180, x, y);
                arrow(canvas, x, y - r * .2f, r, color, true);
                canvas.restore();
            }
            ink.setStyle(Paint.Style.FILL);
        }
    }
}

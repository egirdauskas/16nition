-- Project-owned presentation. No EA scripts, artwork or game state are embedded.
-- Layout uses density-independent units; Android keeps native focus/accessibility.
local ui = {
    version = 1,
    brand = "16NITION",
    context = "FIFA 16 MOBILE",
    colors = {
        background = "#E8EFF3", surface = "#F7FAFC", ink = "#364956",
        muted = "#647986", blue = "#008BC3", blue_dark = "#006A98",
        line = "#CBD8DF", white = "#FFFFFF", green = "#49834C",
    },
    tiles = {
        { id = "play", label = "Play", title = "ULTIMATE TEAM", hint = "PLAY", icon = "pitch" },
        { id = "clubs", label = "Clubs", title = "CLUBS", hint = "SELECT / NEW", icon = "clubs" },
        { id = "import", label = "Import club", title = "IMPORT CLUB", hint = "LOAD A BACKUP", icon = "import" },
        { id = "export", label = "Export club", title = "EXPORT CLUB", hint = "SAVE A BACKUP", icon = "export" },
        { id = "setup", label = "Setup", title = "SETUP", hint = "GAME FILES", icon = "setup" },
        { id = "godmode", label = "GODMODE", title = "GODMODE", hint = "999,999 FP", icon = "points" },
    },
}

function ui.layout(w, h)
    local gap, margin = 8, w < 400 and 14 or 20
    local short = h < 280
    local top, bottom = short and 50 or 70, h - 30
    local frames = {
        logo = {margin, 12, 42, 42},
        brand = {margin + 54, 9, w - margin * 2 - 54, 31},
        context = {margin + 55, 39, w - margin * 2 - 55, 17},
        status = {margin, h - 25, w - margin * 2, 19},
    }
    if short then
        frames.logo = {margin, 8, 34, 34}
        frames.brand = {margin + 46, 5, w - margin * 2 - 46, 27}
        frames.context = {margin + 47, 34, w - margin * 2 - 47, 13}
    end
    if w > h then
        local width = w - margin * 2
        local left = math.floor(width * 0.44)
        local right = width - left - gap
        local x = margin + left + gap
        local half = (right - gap) / 2
        local row = (bottom - top - 48 - gap * 2) / 2
        frames.play = {margin, top, left, bottom - top}
        frames.clubs = {x, top, half, row}
        frames.import = {x + half + gap, top, half, row}
        frames.export = {x, top + row + gap, half, row}
        frames.setup = {x + half + gap, top + row + gap, half, row}
        frames.godmode = {x, bottom - 48, right, 48}
    else
        local width = w - margin * 2
        local hero = math.min(230, (bottom - top) * 0.43)
        local y = top + hero + gap
        local half = (width - gap) / 2
        local row = (bottom - y - 48 - gap * 2) / 2
        frames.play = {margin, top, width, hero}
        frames.clubs = {margin, y, half, row}
        frames.import = {margin + half + gap, y, half, row}
        frames.export = {margin, y + row + gap, half, row}
        frames.setup = {margin + half + gap, y + row + gap, half, row}
        frames.godmode = {margin, bottom - 48, width, 48}
    end
    local play = frames.play
    frames.club = {play[1] + 16, play[2] + 44, play[3] - 32, 30}
    return frames
end

return ui

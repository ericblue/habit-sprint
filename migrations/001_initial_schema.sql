-- Sprints table
CREATE TABLE sprints (
    id TEXT PRIMARY KEY,                    -- slug, e.g. "2026-S01"
    start_date TEXT NOT NULL,               -- ISO 8601, e.g. "2026-01-01"
    end_date TEXT NOT NULL,                 -- ISO 8601, e.g. "2026-01-14"
    theme TEXT,                             -- optional, e.g. "Cut Phase", "Creative Phase"
    focus_goals TEXT DEFAULT '[]',          -- JSON array of strings
    status TEXT NOT NULL DEFAULT 'active',  -- "active" or "archived"
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Habits table
CREATE TABLE habits (
    id TEXT PRIMARY KEY,                    -- slug, e.g. "reading", "daily-walk"
    name TEXT NOT NULL,                     -- display name, e.g. "Reading"
    category TEXT NOT NULL,                 -- e.g. "health", "cognitive", "creative", "projects"
    target_per_week INTEGER NOT NULL,       -- minimum days per week commitment
    weight INTEGER NOT NULL DEFAULT 1,      -- behavioral leverage: 1=low, 2=medium, 3=high
    unit TEXT NOT NULL DEFAULT 'count',     -- "count", "minutes", "reps", "pages"
    sprint_id TEXT,                         -- nullable FK → sprints.id (habit can be global or sprint-scoped)
    archived INTEGER NOT NULL DEFAULT 0,    -- 0=active, 1=archived
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (sprint_id) REFERENCES sprints(id)
);

-- Entries table
CREATE TABLE entries (
    habit_id TEXT NOT NULL,
    date TEXT NOT NULL,                     -- ISO 8601, e.g. "2026-02-28"
    value REAL NOT NULL DEFAULT 1,          -- numeric-first: binary habits use 1, others use actual value
    note TEXT,                              -- optional context
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (habit_id, date),
    FOREIGN KEY (habit_id) REFERENCES habits(id)
);

-- Retrospectives table
CREATE TABLE retros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sprint_id TEXT NOT NULL UNIQUE,         -- one retro per sprint
    what_went_well TEXT,
    what_to_improve TEXT,
    ideas TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (sprint_id) REFERENCES sprints(id)
);

-- Indexes
CREATE INDEX idx_entries_date ON entries(date);
CREATE INDEX idx_entries_habit_date ON entries(habit_id, date);
CREATE INDEX idx_habits_sprint ON habits(sprint_id);
CREATE INDEX idx_habits_category ON habits(category);
CREATE INDEX idx_sprints_status ON sprints(status);

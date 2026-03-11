-- Sprint-specific habit goal overrides (per-sprint target and weight)
CREATE TABLE sprint_habit_goals (
    sprint_id TEXT NOT NULL,
    habit_id TEXT NOT NULL,
    target_per_week INTEGER NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (sprint_id, habit_id),
    FOREIGN KEY (sprint_id) REFERENCES sprints(id),
    FOREIGN KEY (habit_id) REFERENCES habits(id)
);

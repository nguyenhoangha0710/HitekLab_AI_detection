ALTER TABLE rule_config
    ADD COLUMN IF NOT EXISTS object_type varchar(100);

ALTER TABLE rule_config
    ADD COLUMN IF NOT EXISTS use_active_time boolean NOT NULL DEFAULT false;

ALTER TABLE rule_config
    ADD COLUMN IF NOT EXISTS active_start_time time;

ALTER TABLE rule_config
    ADD COLUMN IF NOT EXISTS active_end_time time;

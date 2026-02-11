PRAGMA journal_mode=WAL;


-- AGENTS


CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('human', 'ai', 'system')),
    model TEXT,
    identity TEXT,
    avatar_path TEXT,
    color TEXT,
    created_at TEXT NOT NULL,
    archived_at TEXT,
    deleted_at TEXT,
    merged_into TEXT REFERENCES agents(id)
);

CREATE INDEX idx_agents_handle ON agents(handle);
CREATE INDEX idx_agents_type ON agents(type);
CREATE INDEX idx_agents_archived ON agents(archived_at);
CREATE INDEX idx_agents_merged_into ON agents(merged_into);


-- PROJECTS


CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('standard', 'proto', 'customer')),
    repo_path TEXT UNIQUE,
    github_login TEXT,
    repo_url TEXT,
    provisioned_at TEXT,
    color TEXT,
    icon TEXT,
    tags TEXT,
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE INDEX idx_projects_github_login ON projects(github_login);
CREATE INDEX idx_projects_type ON projects(type);


-- DEVICES


CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    tailscale_ip TEXT NOT NULL UNIQUE,
    push_token TEXT,
    name TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_devices_owner ON devices(owner_id);
CREATE INDEX idx_devices_tailscale_ip ON devices(tailscale_ip);


-- SPAWNS


CREATE TABLE spawns (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    caller_spawn_id TEXT REFERENCES spawns(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK(status IN ('active', 'done')),
    mode TEXT NOT NULL CHECK(mode IN ('sovereign', 'directed')) DEFAULT 'sovereign',
    error TEXT,
    pid INTEGER,
    session_id TEXT,
    summary TEXT,
    trace_hash TEXT,
    resume_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_active_at TEXT
);

CREATE INDEX idx_spawns_agent ON spawns(agent_id);
CREATE INDEX idx_spawns_caller ON spawns(caller_spawn_id);
CREATE INDEX idx_spawns_status_pid ON spawns(status, pid);
CREATE INDEX idx_spawns_status_created ON spawns(status, created_at);
CREATE UNIQUE INDEX idx_spawns_global_singleton ON spawns(agent_id) WHERE status = 'active' AND mode = 'sovereign';


-- DECISIONS


CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    spawn_id TEXT REFERENCES spawns(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    rationale TEXT NOT NULL,
    expected_outcome TEXT,
    reversible INTEGER,
    outcome TEXT,
    refs TEXT,
    images TEXT,
    created_at TEXT NOT NULL,
    committed_at TEXT,
    actioned_at TEXT,
    rejected_at TEXT,
    archived_at TEXT,
    deleted_at TEXT
);

CREATE INDEX idx_decisions_project ON decisions(project_id);
CREATE INDEX idx_decisions_agent ON decisions(agent_id);
CREATE INDEX idx_decisions_spawn ON decisions(spawn_id);
CREATE INDEX idx_decisions_created ON decisions(created_at DESC);
CREATE INDEX idx_decisions_committed ON decisions(committed_at);
CREATE INDEX idx_decisions_archived ON decisions(archived_at);
CREATE INDEX idx_decisions_deleted ON decisions(deleted_at);


-- INSIGHTS


CREATE TABLE insights (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    spawn_id TEXT REFERENCES spawns(id) ON DELETE SET NULL,
    decision_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    domain TEXT NOT NULL,
    content TEXT NOT NULL CHECK(length(content) <= 280),
    mentions TEXT,
    images TEXT,
    open INTEGER NOT NULL DEFAULT 0,
    provenance TEXT CHECK(provenance IN ('solo', 'collaborative', 'synthesis')),
    counterfactual INTEGER,
    created_at TEXT NOT NULL,
    archived_at TEXT,
    deleted_at TEXT
);

CREATE INDEX idx_insights_project ON insights(project_id);
CREATE INDEX idx_insights_agent ON insights(agent_id);
CREATE INDEX idx_insights_spawn ON insights(spawn_id);
CREATE INDEX idx_insights_decision ON insights(decision_id);
CREATE INDEX idx_insights_domain ON insights(domain);
CREATE INDEX idx_insights_created ON insights(created_at);
CREATE INDEX idx_insights_open ON insights(open) WHERE open = 1;
CREATE INDEX idx_insights_provenance ON insights(provenance) WHERE provenance IS NOT NULL;


-- TASKS


CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    decision_id TEXT REFERENCES decisions(id) ON DELETE RESTRICT,
    creator_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    assignee_id TEXT REFERENCES agents(id) ON DELETE SET NULL,
    spawn_id TEXT REFERENCES spawns(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'active', 'done', 'cancelled')),
    result TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    deleted_at TEXT
);

CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_decision ON tasks(decision_id);
CREATE INDEX idx_tasks_creator ON tasks(creator_id);
CREATE INDEX idx_tasks_assignee ON tasks(assignee_id);
CREATE INDEX idx_tasks_spawn ON tasks(spawn_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created ON tasks(created_at);


-- REPLIES


CREATE TABLE replies (
    id TEXT PRIMARY KEY,
    parent_type TEXT NOT NULL CHECK(parent_type IN ('insight', 'decision', 'task')),
    parent_id TEXT NOT NULL,
    author_id TEXT NOT NULL REFERENCES agents(id),
    spawn_id TEXT REFERENCES spawns(id),
    project_id TEXT REFERENCES projects(id),
    content TEXT NOT NULL,
    mentions TEXT,
    images TEXT,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX idx_replies_parent ON replies(parent_type, parent_id);
CREATE INDEX idx_replies_author ON replies(author_id);
CREATE INDEX idx_replies_mentions ON replies(mentions);
CREATE INDEX idx_replies_created ON replies(created_at DESC);



-- CITATIONS


CREATE TABLE citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL CHECK(source_type IN ('insight', 'decision', 'reply', 'spawn')),
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('insight', 'decision')),
    target_short_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_citations_source ON citations(source_type, source_id);
CREATE INDEX idx_citations_target ON citations(target_type, target_short_id);
CREATE UNIQUE INDEX idx_citations_unique ON citations(source_type, source_id, target_type, target_short_id);


-- EMAILS


CREATE TABLE emails (
    id TEXT PRIMARY KEY,
    resend_id TEXT UNIQUE,
    direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
    from_addr TEXT NOT NULL,
    to_addr TEXT NOT NULL,
    subject TEXT,
    body_text TEXT,
    body_html TEXT,
    status TEXT DEFAULT 'sent' CHECK(status IN ('draft', 'approved', 'sent', 'rejected')),
    approved_by TEXT REFERENCES agents(id),
    approved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_emails_direction ON emails(direction);
CREATE INDEX idx_emails_from ON emails(from_addr);
CREATE INDEX idx_emails_status ON emails(status);
CREATE INDEX idx_emails_created ON emails(created_at DESC);


-- HEALTH METRICS


CREATE TABLE health_metrics (
    id TEXT PRIMARY KEY,
    score INTEGER NOT NULL,
    lint_violations INTEGER NOT NULL DEFAULT 0,
    type_errors INTEGER NOT NULL DEFAULT 0,
    test_passed INTEGER NOT NULL DEFAULT 0,
    test_failed INTEGER NOT NULL DEFAULT 0,
    arch_violations INTEGER NOT NULL DEFAULT 0,
    suppressions INTEGER NOT NULL DEFAULT 0,
    stashes INTEGER NOT NULL DEFAULT 0,
    project_id TEXT REFERENCES projects(id),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_health_metrics_created ON health_metrics(created_at);
CREATE INDEX idx_health_metrics_project ON health_metrics(project_id);


-- ACTIVITY


CREATE TABLE activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    spawn_id TEXT,
    primitive TEXT NOT NULL CHECK(primitive IN ('decision', 'insight', 'task', 'reply', 'spawn')),
    primitive_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('created', 'archived', 'linked', 'claimed', 'released', 'completed', 'cancelled', 'resolved', 'rejected', 'started', 'failed')),
    field TEXT,
    before TEXT,
    after TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_activity_agent ON activity(agent_id);
CREATE INDEX idx_activity_primitive ON activity(primitive, primitive_id);
CREATE INDEX idx_activity_created ON activity(created_at);


-- FTS: SPAWNS


CREATE VIRTUAL TABLE spawns_fts USING fts5(id UNINDEXED, summary);

CREATE TRIGGER spawns_fts_ai AFTER INSERT ON spawns BEGIN
    INSERT INTO spawns_fts(id, summary) VALUES (new.id, new.summary);
END;

CREATE TRIGGER spawns_fts_ad AFTER DELETE ON spawns BEGIN
    DELETE FROM spawns_fts WHERE id = old.id;
END;

CREATE TRIGGER spawns_fts_au AFTER UPDATE ON spawns BEGIN
    DELETE FROM spawns_fts WHERE id = old.id;
    INSERT INTO spawns_fts(id, summary) VALUES (new.id, new.summary);
END;


-- FTS: DECISIONS


CREATE VIRTUAL TABLE decisions_fts USING fts5(id UNINDEXED, content, rationale);

CREATE TRIGGER decisions_fts_ai AFTER INSERT ON decisions BEGIN
    INSERT INTO decisions_fts(id, content, rationale) VALUES (new.id, new.content, new.rationale);
END;

CREATE TRIGGER decisions_fts_ad AFTER DELETE ON decisions BEGIN
    DELETE FROM decisions_fts WHERE id = old.id;
END;

CREATE TRIGGER decisions_fts_au AFTER UPDATE ON decisions BEGIN
    DELETE FROM decisions_fts WHERE id = old.id;
    INSERT INTO decisions_fts(id, content, rationale) VALUES (new.id, new.content, new.rationale);
END;


-- FTS: INSIGHTS


CREATE VIRTUAL TABLE insights_fts USING fts5(id UNINDEXED, content, domain);

CREATE TRIGGER insights_fts_ai AFTER INSERT ON insights BEGIN
    INSERT INTO insights_fts(id, content, domain) VALUES (new.id, new.content, new.domain);
END;

CREATE TRIGGER insights_fts_ad AFTER DELETE ON insights BEGIN
    DELETE FROM insights_fts WHERE id = old.id;
END;

CREATE TRIGGER insights_fts_au AFTER UPDATE ON insights WHEN new.deleted_at IS NULL BEGIN
    DELETE FROM insights_fts WHERE id = old.id;
    INSERT INTO insights_fts(id, content, domain) VALUES (new.id, new.content, new.domain);
END;

CREATE TRIGGER insights_fts_au_delete AFTER UPDATE ON insights WHEN new.deleted_at IS NOT NULL AND old.deleted_at IS NULL BEGIN
    DELETE FROM insights_fts WHERE id = old.id;
END;


-- FTS: TASKS


CREATE VIRTUAL TABLE tasks_fts USING fts5(id UNINDEXED, content, result);

CREATE TRIGGER tasks_fts_ai AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts(id, content, result) VALUES (new.id, new.content, new.result);
END;

CREATE TRIGGER tasks_fts_ad AFTER DELETE ON tasks BEGIN
    DELETE FROM tasks_fts WHERE id = old.id;
END;

CREATE TRIGGER tasks_fts_au AFTER UPDATE ON tasks BEGIN
    DELETE FROM tasks_fts WHERE id = old.id;
    INSERT INTO tasks_fts(id, content, result) VALUES (new.id, new.content, new.result);
END;


-- FTS: REPLIES


CREATE VIRTUAL TABLE replies_fts USING fts5(id UNINDEXED, content);

CREATE TRIGGER replies_fts_ai AFTER INSERT ON replies BEGIN
    INSERT INTO replies_fts(id, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER replies_fts_ad AFTER DELETE ON replies BEGIN
    DELETE FROM replies_fts WHERE id = old.id;
END;

CREATE TRIGGER replies_fts_au AFTER UPDATE ON replies BEGIN
    DELETE FROM replies_fts WHERE id = old.id;
    INSERT INTO replies_fts(id, content) VALUES (new.id, new.content);
END;



-- TRIGGERS: SPAWN


CREATE TRIGGER spawn_started AFTER INSERT ON spawns BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.agent_id, NEW.id, 'spawn', NEW.id, 'started', NEW.created_at);
END;

CREATE TRIGGER spawn_completed AFTER UPDATE OF status ON spawns
WHEN OLD.status = 'active' AND NEW.status = 'done' AND NEW.error IS NULL BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.agent_id, NEW.id, 'spawn', NEW.id, 'completed', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

CREATE TRIGGER spawn_failed AFTER UPDATE OF status ON spawns
WHEN OLD.status = 'active' AND NEW.status = 'done' AND NEW.error IS NOT NULL BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, field, after, created_at)
    VALUES (NEW.agent_id, NEW.id, 'spawn', NEW.id, 'failed', 'error', NEW.error, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;


-- TRIGGERS: DECISION


CREATE TRIGGER decision_created AFTER INSERT ON decisions BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.agent_id, NEW.spawn_id, 'decision', NEW.id, 'created', NEW.created_at);
END;

CREATE TRIGGER decision_archived AFTER UPDATE OF archived_at ON decisions
WHEN OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.agent_id, NEW.spawn_id, 'decision', NEW.id, 'archived', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;


-- TRIGGERS: INSIGHT


CREATE TRIGGER insight_created AFTER INSERT ON insights BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'created', NEW.created_at);
END;

CREATE TRIGGER insight_archived AFTER UPDATE OF archived_at ON insights
WHEN OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'archived', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

CREATE TRIGGER insight_linked AFTER UPDATE OF decision_id ON insights
WHEN OLD.decision_id IS NULL AND NEW.decision_id IS NOT NULL BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, field, after, created_at)
    VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'linked', 'decision_id', NEW.decision_id, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;

CREATE TRIGGER insight_resolved AFTER UPDATE OF open ON insights
WHEN OLD.open = 1 AND NEW.open = 0 BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.agent_id, NEW.spawn_id, 'insight', NEW.id, 'resolved', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;


-- TRIGGERS: TASK


CREATE TRIGGER task_created AFTER INSERT ON tasks BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.creator_id, NEW.spawn_id, 'task', NEW.id, 'created', NEW.created_at);
END;

CREATE TRIGGER task_status_change AFTER UPDATE OF status ON tasks
WHEN OLD.status != NEW.status BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, field, before, after, created_at)
    VALUES (
        COALESCE(NEW.assignee_id, NEW.creator_id), NEW.spawn_id, 'task', NEW.id,
        CASE NEW.status WHEN 'active' THEN 'claimed' WHEN 'done' THEN 'completed'
            WHEN 'cancelled' THEN 'cancelled' WHEN 'pending' THEN 'released' END,
        'status', OLD.status, NEW.status, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    );
END;


-- TRIGGERS: REPLY


CREATE TRIGGER reply_created AFTER INSERT ON replies BEGIN
    INSERT INTO activity (agent_id, spawn_id, primitive, primitive_id, action, created_at)
    VALUES (NEW.author_id, NEW.spawn_id, 'reply', NEW.id, 'created', NEW.created_at);
END;


-- HUMAN RESOLUTIONS


CREATE TABLE IF NOT EXISTS human_resolutions (
    artifact_type TEXT NOT NULL CHECK(artifact_type IN ('insight', 'decision', 'task')),
    artifact_id TEXT NOT NULL,
    resolved_by TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    resolved_at TEXT NOT NULL,
    PRIMARY KEY (artifact_type, artifact_id)
);

CREATE INDEX idx_human_resolutions_resolved_at ON human_resolutions(resolved_at);


-- ARTIFACT READS


CREATE TABLE IF NOT EXISTS artifact_reads (
  artifact_type TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  spawn_id TEXT,
  read_at TEXT NOT NULL,
  PRIMARY KEY (artifact_type, artifact_id, agent_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_artifact_reads_agent ON artifact_reads(agent_id);
CREATE INDEX IF NOT EXISTS idx_artifact_reads_artifact ON artifact_reads(artifact_type, artifact_id);


-- CLI INVOCATIONS


CREATE TABLE IF NOT EXISTS cli_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    spawn_id TEXT,
    command TEXT NOT NULL,
    args TEXT,
    exit_code INTEGER NOT NULL,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_cli_invocations_spawn ON cli_invocations(spawn_id);
CREATE INDEX idx_cli_invocations_command ON cli_invocations(command);
CREATE INDEX idx_cli_invocations_exit ON cli_invocations(exit_code);
CREATE INDEX idx_cli_invocations_ts ON cli_invocations(ts);



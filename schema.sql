CREATE DATABASE IF NOT EXISTS vpm_db;
USE vpm_db;


CREATE TABLE agent_episodes (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	agent_id VARCHAR(100) NOT NULL, 
	session_id VARCHAR(100) NOT NULL, 
	timestamp DATETIME, 
	event_type VARCHAR(50) NOT NULL, 
	content TEXT NOT NULL, 
	metadata_json JSON, 
	PRIMARY KEY (id)
)

;


CREATE TABLE agent_run_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	agent_id VARCHAR(100) NOT NULL, 
	session_id VARCHAR(100), 
	status VARCHAR(50) NOT NULL, 
	latency_ms FLOAT, 
	tokens_used INTEGER, 
	error_message TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id)
)

;


CREATE TABLE approval_queue (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	action_type VARCHAR(100) NOT NULL, 
	payload JSON NOT NULL, 
	status VARCHAR(50), 
	reasoning TEXT, 
	created_at DATETIME, 
	resolved_at DATETIME, 
	PRIMARY KEY (id)
)

;


CREATE TABLE procedural_patterns (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	pattern_name VARCHAR(100) NOT NULL, 
	description TEXT, 
	steps_json JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (pattern_name)
)

;


CREATE TABLE programs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id)
)

;


CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
)

;


CREATE TABLE dashboard_snapshots (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	program_id INTEGER, 
	data JSON NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(program_id) REFERENCES programs (id)
)

;


CREATE TABLE projects (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	program_id INTEGER NOT NULL, 
	jira_key VARCHAR(50) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	status VARCHAR(50), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(program_id) REFERENCES programs (id), 
	UNIQUE (jira_key)
)

;


CREATE TABLE budgets (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	project_id INTEGER NOT NULL, 
	period VARCHAR(50) NOT NULL, 
	planned_spend NUMERIC(12, 2) NOT NULL, 
	actual_spend NUMERIC(12, 2) NOT NULL, 
	variance NUMERIC(12, 2) NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
)

;


CREATE TABLE kpis (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	program_id INTEGER, 
	project_id INTEGER, 
	metric_name VARCHAR(100) NOT NULL, 
	metric_value FLOAT NOT NULL, 
	trend FLOAT, 
	trend_label VARCHAR(100), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(program_id) REFERENCES programs (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
)

;


CREATE TABLE risk_register (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	project_id INTEGER NOT NULL, 
	risk_id VARCHAR(50) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT NOT NULL, 
	severity VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	owner VARCHAR(100) DEFAULT 'Unassigned',
	mitigation_plan TEXT, 
	jira_issue_key VARCHAR(50),
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE TABLE guardrail_policies (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	policy_id VARCHAR(50) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	description TEXT, 
	status VARCHAR(50) DEFAULT 'Active', 
	level VARCHAR(50) DEFAULT 'Medium', 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (policy_id)
);

CREATE TABLE integration_settings (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	provider VARCHAR(50) NOT NULL, 
	base_url VARCHAR(255), 
	username_email VARCHAR(255), 
	api_token VARCHAR(255), 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (provider)
);

-- ==========================================
-- DEFAULT INITIAL SEED DATA
-- ==========================================

-- 1. Initial Users (password123 hashed with Werkzeug scrypt)
INSERT INTO users (id, email, password_hash, `role`) VALUES
(1, 'pmo@example.com', 'scrypt:32768:8:1$itKfZmQfl8ncSB4P$65595e50f5837a87ee6d2f72e42b6756d99918a0b6380293de8c58acb0943e136b45c020e213c42f12bec0dd45d2bbcb06afdab8b0967b2525a5f4e253fd8d61', 'PMO'),
(2, 'investor@example.com', 'scrypt:32768:8:1$itKfZmQfl8ncSB4P$65595e50f5837a87ee6d2f72e42b6756d99918a0b6380293de8c58acb0943e136b45c020e213c42f12bec0dd45d2bbcb06afdab8b0967b2525a5f4e253fd8d61', 'Investor'),
(3, 'director@example.com', 'scrypt:32768:8:1$itKfZmQfl8ncSB4P$65595e50f5837a87ee6d2f72e42b6756d99918a0b6380293de8c58acb0943e136b45c020e213c42f12bec0dd45d2bbcb06afdab8b0967b2525a5f4e253fd8d61', 'Program Director'),
(4, 'pm@example.com', 'scrypt:32768:8:1$itKfZmQfl8ncSB4P$65595e50f5837a87ee6d2f72e42b6756d99918a0b6380293de8c58acb0943e136b45c020e213c42f12bec0dd45d2bbcb06afdab8b0967b2525a5f4e253fd8d61', 'Project Manager')
ON DUPLICATE KEY UPDATE email=email;

-- 2. Initial Program & Projects
INSERT INTO programs (id, name, description, created_at) VALUES
(1, 'Alpha Migration', 'Migrating core legacy monolithic services to cloud microservices', NOW())
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO projects (id, program_id, jira_key, name, status, created_at) VALUES
(1, 1, 'PRJ-101', 'Frontend Rewrite', 'Active', NOW()),
(2, 1, 'PRJ-102', 'Cloud Infrastructure Migration', 'Active', NOW())
ON DUPLICATE KEY UPDATE jira_key=jira_key;

-- 3. Initial Budgets
INSERT INTO budgets (id, project_id, period, planned_spend, actual_spend, variance, created_at) VALUES
(1, 1, 'Q1 2026', 1500000.00, 1200000.00, -300000.00, NOW()),
(2, 2, 'Q1 2026', 850000.00, 620000.00, -230000.00, NOW())
ON DUPLICATE KEY UPDATE id=id;

-- 4. Initial Risks
INSERT INTO risk_register (id, project_id, risk_id, title, description, severity, status, mitigation_plan, created_at) VALUES
(1, 1, 'R-102', 'API Security Vulnerability', 'Potential injection flaw in proxy', 'Critical', 'Open', 'Apply patch and rotate keys', NOW()),
(2, 1, 'R-145', 'Budget Overrun in Q3', 'Contractor expenses higher than planned', 'Critical', 'Open', 'Reallocate contingency buffer', NOW()),
(3, 1, 'R-099', 'Vendor delivery delay', 'Hardware delivery delayed by supplier', 'High', 'Mitigated', 'Order from secondary vendor', NOW()),
(4, 1, 'R-042', 'Resource constraint on frontend', 'Shortage of React engineers', 'Medium', 'Open', 'Staff augmentation', NOW()),
(5, 1, 'R-011', 'Minor scope creep', 'Extra analytics widget requested', 'Low', 'Closed', 'Deferred to next release', NOW()),
(6, 2, 'R-201', 'Kubernetes Cluster Upgrade Lag', 'EKS version out of support date', 'Critical', 'Open', 'Blue/green cluster upgrade planned', NOW()),
(7, 2, 'R-202', 'Egress Cost Spikes', 'Inter-region DB replication data transfer costs', 'High', 'Open', 'Implement VPC peering endpoint', NOW()),
(8, 2, 'R-203', 'Terraform Lock Contention', 'Concurrent CI pipeline deployments colliding', 'Medium', 'Mitigated', 'State locking with DynamoDB', NOW()),
(9, 2, 'R-204', 'Staging SSL Cert Expiry', 'Automated certbot renewal failed', 'Low', 'Closed', 'Renewed with manual DNS challenge', NOW())
ON DUPLICATE KEY UPDATE id=id;

-- 5. Default Guardrail Policies
INSERT INTO guardrail_policies (id, policy_id, name, category, description, status, level, created_at) VALUES
(1, 'POL-001', 'Input Schema Enforcement', 'Data Integrity', 'All agent input payloads must conform to strict Pydantic models before execution.', 'Active', 'Strict', NOW()),
(2, 'POL-002', 'Output Structure Validation', 'Safety & Format', 'Validates that LLM JSON output satisfies target agent schemas; rejects malformed output.', 'Active', 'Strict', NOW()),
(3, 'POL-003', 'Risk Escalation Threshold', 'Human-in-the-Loop', 'Risks with Critical severity or confidence scores below 70% automatically route to PMO approval queue.', 'Active', 'High', NOW()),
(4, 'POL-004', 'Budget Variance Guardrail', 'Financial Controls', 'Calculates variance and flags trajectories exceeding 10% budget burn deviation.', 'Active', 'Warning', NOW()),
(5, 'POL-005', 'Prompt Injection Mitigation', 'Security', 'Sanitizes raw document text and system prompts before model invocation.', 'Active', 'Strict', NOW())
ON DUPLICATE KEY UPDATE policy_id=policy_id;

-- 6. Initial Approval Queue Items
INSERT INTO approval_queue (id, action_type, payload, status, reasoning, created_at) VALUES
(1, 'Budget Variance Override', '{"project_id": "PRJ-101", "amount": 50000, "reason": "Additional security compliance audit"}', 'Pending', 'Requested by PMO lead', NOW()),
(2, 'Risk Acceptance', '{"risk_id": "R-102", "project_id": "PRJ-101", "waiver_days": 14}', 'Pending', 'Patch requires staging soak test', NOW())
ON DUPLICATE KEY UPDATE id=id;

-- 7. Initial Dashboard Snapshot
INSERT INTO dashboard_snapshots (id, program_id, data, created_at) VALUES
(1, 1, '{"name": "Alpha Migration Program", "id": "PRJ-101", "kpis": [{"title": "Program Budget", "value": "$1.2M / $1.5M", "trend": "up", "trendLabel": "80% Burned"}, {"title": "Budget Variance", "value": "$300K Surplus", "trend": "down", "trendLabel": "Under Budget"}, {"title": "Active Risks", "value": "4", "trend": "up", "trendLabel": "2 Critical"}, {"title": "Overall Health", "value": "75%", "trend": "neutral", "trendLabel": "Moderate Risk"}], "burndown": [{"sprint": "Sprint 1", "planned": 100, "actual": 95}, {"sprint": "Sprint 2", "planned": 80, "actual": 82}, {"sprint": "Sprint 3", "planned": 60, "actual": 65}, {"sprint": "Sprint 4", "planned": 40, "actual": 40}, {"sprint": "Sprint 5", "planned": 20, "actual": 18}, {"sprint": "Sprint 6", "planned": 0, "actual": null}], "risks": [{"label": "Critical", "color": "bg-primary", "items": ["R-102", "R-145"]}, {"label": "High", "color": "bg-button", "items": ["R-099"]}, {"label": "Medium", "color": "bg-hover", "items": ["R-042"]}, {"label": "Low", "color": "bg-borderOrange", "items": ["R-011"]}], "financials": {"totalBudget": 1500000, "spent": 1200000, "remaining": 300000, "projectedVariance": -50000}, "milestones": [{"name": "Architecture Sign-off", "date": "Jan 15", "status": "completed"}, {"name": "MVP Delivery", "date": "Feb 28", "status": "completed"}, {"name": "Beta Rollout", "date": "Mar 30", "status": "in-progress"}, {"name": "Full Migration", "date": "Apr 30", "status": "pending"}]}', NOW())
ON DUPLICATE KEY UPDATE id=id;




"""Jalase-Negar gamification: badges with limited gift tokens, and friend invites.

`jalase_achievements` is the admin-managed catalogue (metric, threshold, gift tokens);
`jalase_earned_achievements` records which badge a personal account earned and how many gift
tokens it actually received (the monthly cap can reduce it to zero).  Invite codes and their
redemptions are platform-level (control) tables.  Gift tokens are `token_grants` rows with the
new sources `reward` and `invite`.
"""

from alembic import op

revision = "0152_jalase_gamification"
down_revision = "0151_jalase_plans_help"
branch_labels = None
depends_on = None

POLICY = """USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')"""

METRICS = ("meetings", "documents", "categories", "streak_weeks")

# code, title, description, metric, threshold, gift tokens, sort order
SEEDS = (
    ("first_meeting", "اولین جلسه", "اولین جلسه‌تان را ثبت کردید.", "meetings", 1, 5_000, 10),
    ("five_meetings", "پنج جلسه", "پنج جلسه ثبت کرده‌اید.", "meetings", 5, 10_000, 20),
    ("twenty_meetings", "بیست جلسه", "بیست جلسه ثبت کرده‌اید.", "meetings", 20, 30_000, 30),
    ("first_document", "اولین سند", "اولین سند را از جلسه ساختید.", "documents", 1, 5_000, 40),
    ("ten_documents", "ده سند", "ده سند ساخته‌اید.", "documents", 10, 15_000, 50),
    (
        "three_categories",
        "کاوشگر دسته‌ها",
        "سه دستهٔ مختلف را امتحان کردید.",
        "categories",
        3,
        10_000,
        60,
    ),
    (
        "streak_2_weeks",
        "دو هفتهٔ پیاپی",
        "دو هفتهٔ پشت‌سرهم جلسه داشتید.",
        "streak_weeks",
        2,
        10_000,
        70,
    ),
    (
        "streak_4_weeks",
        "چهار هفتهٔ پیاپی",
        "چهار هفتهٔ پشت‌سرهم جلسه داشتید.",
        "streak_weeks",
        4,
        25_000,
        80,
    ),
)


def upgrade() -> None:
    op.execute("ALTER TABLE token_grants DROP CONSTRAINT IF EXISTS token_grants_source_check")
    op.execute(
        "ALTER TABLE token_grants ADD CONSTRAINT token_grants_source_check "
        "CHECK (source IN ('purchase','admin_adjustment','reward','invite'))"
    )
    metrics = ",".join(f"'{m}'" for m in METRICS)
    op.execute(f"""CREATE TABLE jalase_achievements (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        code varchar(48) NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9_]{{2,48}}$'),
        title_fa text NOT NULL,
        description_fa text NOT NULL,
        metric varchar(24) NOT NULL CHECK (metric IN ({metrics})),
        threshold integer NOT NULL CHECK (threshold >= 1),
        reward_tokens integer NOT NULL DEFAULT 0 CHECK (reward_tokens >= 0),
        active boolean NOT NULL DEFAULT true,
        sort_order integer NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""CREATE TABLE jalase_earned_achievements (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        achievement_code varchar(48) NOT NULL,
        reward_tokens integer NOT NULL DEFAULT 0,
        earned_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, achievement_code))""")
    op.execute("CREATE INDEX idx_jalase_earned_tenant ON jalase_earned_achievements (tenant_id)")
    op.execute("""CREATE TABLE jalase_invite_codes (
        tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
        code varchar(12) NOT NULL UNIQUE,
        created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""CREATE TABLE jalase_invite_redemptions (
        invitee_tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
        inviter_tenant_id uuid NOT NULL REFERENCES tenants(id),
        reward_tokens integer NOT NULL,
        invitee_granted boolean NOT NULL DEFAULT false,
        inviter_granted boolean NOT NULL DEFAULT false,
        redeemed_at timestamptz NOT NULL DEFAULT now())""")
    op.execute(
        "CREATE INDEX idx_jalase_invites_inviter ON jalase_invite_redemptions (inviter_tenant_id)"
    )
    for table in (
        "jalase_achievements",
        "jalase_invite_codes",
        "jalase_invite_redemptions",
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_earned_achievements TO cbi_app")
    op.execute("ALTER TABLE jalase_earned_achievements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE jalase_earned_achievements FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY jalase_earned_achievements_tenant_isolation "
        f"ON jalase_earned_achievements {POLICY}"
    )
    for code, title, description, metric, threshold, reward, order in SEEDS:
        op.execute(
            "INSERT INTO jalase_achievements (code, title_fa, description_fa, metric, "
            f"threshold, reward_tokens, sort_order) VALUES ('{code}', '{title}', "
            f"'{description}', '{metric}', {threshold}, {reward}, {order}) "
            "ON CONFLICT (code) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jalase_invite_redemptions")
    op.execute("DROP TABLE IF EXISTS jalase_invite_codes")
    op.execute("DROP TABLE IF EXISTS jalase_earned_achievements")
    op.execute("DROP TABLE IF EXISTS jalase_achievements")
    op.execute("DELETE FROM token_grants WHERE source IN ('reward','invite')")
    op.execute("ALTER TABLE token_grants DROP CONSTRAINT IF EXISTS token_grants_source_check")
    op.execute(
        "ALTER TABLE token_grants ADD CONSTRAINT token_grants_source_check "
        "CHECK (source IN ('purchase','admin_adjustment'))"
    )

--
-- FROZEN SNAPSHOT — part of the 20260626_0125 baseline migration record.
-- The shared/public schema as the collapsed post-squash chain builds it
-- (superadmin policy legs stripped; app_admin/app_user grants at their audited
-- matrices; no future-table default privileges for the login roles), MINUS the
-- legacy public copies of guild-content tables (fresh installs never create
-- those; guild content lives only in guild_<id> schemas / guild_template).
-- Generated once with pg_dump and curated; never regenerate or edit. Later
-- shared-schema changes are ordinary new migrations. Role names
-- `platform_base` / `platform_<tier>` are templated with
-- settings.PLATFORM_ROLE_PREFIX by the baseline migration at apply time.
--

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: pg_database_owner
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: counter_view_mode; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.counter_view_mode AS ENUM (
    'number',
    'progress_bar',
    'segmented_clock'
);



--
-- Name: document_type; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.document_type AS ENUM (
    'native',
    'file',
    'whiteboard',
    'smart_link',
    'spreadsheet'
);



--
-- Name: guild_role; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.guild_role AS ENUM (
    'admin',
    'member'
);



--
-- Name: property_type; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.property_type AS ENUM (
    'text',
    'number',
    'checkbox',
    'date',
    'datetime',
    'url',
    'select',
    'multi_select',
    'user_reference'
);



--
-- Name: rsvp_status; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.rsvp_status AS ENUM (
    'pending',
    'accepted',
    'declined',
    'tentative'
);



--
-- Name: task_priority; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.task_priority AS ENUM (
    'low',
    'medium',
    'high',
    'urgent'
);



--
-- Name: task_status_category; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.task_status_category AS ENUM (
    'backlog',
    'todo',
    'in_progress',
    'done'
);



--
-- Name: user_role; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.user_role AS ENUM (
    'admin',
    'member',
    'support',
    'moderator',
    'owner'
);



--
-- Name: user_status; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.user_status AS ENUM (
    'active',
    'deactivated',
    'anonymized'
);



--
-- Name: user_token_purpose; Type: TYPE; Schema: public; Owner: initiative
--

CREATE TYPE public.user_token_purpose AS ENUM (
    'email_verification',
    'password_reset',
    'device_auth'
);



--
-- Name: fn_comments_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_comments_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR
               (TG_OP = 'UPDATE' AND (OLD.task_id IS DISTINCT FROM NEW.task_id OR OLD.document_id IS DISTINCT FROM NEW.document_id)) THEN
                IF NEW.task_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
                ELSIF NEW.document_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id FROM documents WHERE id = NEW.document_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_documents_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_documents_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_initiative_members_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_initiative_members_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_project_documents_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_project_documents_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_project_favorites_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_project_favorites_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_project_orders_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_project_orders_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_projects_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_projects_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.initiative_id IS DISTINCT FROM NEW.initiative_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM initiatives WHERE id = NEW.initiative_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_recent_views_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_recent_views_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND (
                OLD.entity_type IS DISTINCT FROM NEW.entity_type
                OR OLD.entity_id IS DISTINCT FROM NEW.entity_id
            )) THEN
                CASE NEW.entity_type
                    WHEN 'project' THEN
                        SELECT guild_id INTO NEW.guild_id FROM projects
                        WHERE id = NEW.entity_id;
                    WHEN 'document' THEN
                        SELECT guild_id INTO NEW.guild_id FROM documents
                        WHERE id = NEW.entity_id;
                    WHEN 'queue' THEN
                        SELECT guild_id INTO NEW.guild_id FROM queues
                        WHERE id = NEW.entity_id;
                    WHEN 'counter_group' THEN
                        SELECT guild_id INTO NEW.guild_id FROM counter_groups
                        WHERE id = NEW.entity_id;
                END CASE;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_subtasks_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_subtasks_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.task_id IS DISTINCT FROM NEW.task_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_task_assignees_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_task_assignees_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.task_id IS DISTINCT FROM NEW.task_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM tasks WHERE id = NEW.task_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_task_statuses_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_task_statuses_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: fn_tasks_set_guild_id(); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.fn_tasks_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id) THEN
                SELECT guild_id INTO NEW.guild_id FROM projects WHERE id = NEW.project_id;
            END IF;
            RETURN NEW;
        END;
        $$;



--
-- Name: initiative_access(integer, integer, boolean); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        current_setting('app.current_guild_role'::text, true) = 'admin'::text
        OR (CASE
              WHEN p_need_write
                THEN current_setting('app.pam_write'::text, true) = 'true'::text
              ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                   OR current_setting('app.pam_write'::text, true) = 'true'::text
            END)
        OR EXISTS (
            SELECT 1 FROM initiative_members im
            WHERE im.initiative_id = p_initiative_id
              AND im.user_id = p_user_id
        )
$$;



--
-- Name: reorder_guild_memberships(integer, integer[]); Type: FUNCTION; Schema: public; Owner: initiative
--

CREATE FUNCTION public.reorder_guild_memberships(p_user_id integer, p_guild_ids integer[]) RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
            UPDATE guild_memberships gm
            SET position = ord.idx - 1
            FROM unnest(p_guild_ids) WITH ORDINALITY AS ord(guild_id, idx)
            WHERE gm.user_id = p_user_id AND gm.guild_id = ord.guild_id;
        $$;



SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_grants; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.access_grants (
    id integer NOT NULL,
    user_id integer NOT NULL,
    guild_id integer NOT NULL,
    access_level character varying(16) DEFAULT 'read'::character varying NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    reason text NOT NULL,
    requested_duration_minutes integer NOT NULL,
    requested_by_id integer NOT NULL,
    approved_by_id integer,
    revoked_by_id integer,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    decided_at timestamp with time zone,
    expires_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_access_grants_access_level CHECK (((access_level)::text = ANY (ARRAY[('read'::character varying)::text, ('read_write'::character varying)::text]))),
    CONSTRAINT ck_access_grants_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('approved'::character varying)::text, ('denied'::character varying)::text, ('revoked'::character varying)::text, ('expired'::character varying)::text])))
);

ALTER TABLE ONLY public.access_grants FORCE ROW LEVEL SECURITY;



--
-- Name: access_grants_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.access_grants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: access_grants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.access_grants_id_seq OWNED BY public.access_grants.id;


--
-- Name: user_api_keys; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.user_api_keys (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(100) NOT NULL,
    token_prefix character varying(16) NOT NULL,
    token_hash character varying(128) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    read_only boolean NOT NULL,
    guild_id integer
);



--
-- Name: admin_api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.admin_api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: admin_api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.admin_api_keys_id_seq OWNED BY public.user_api_keys.id;


--
-- Name: app_settings; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.app_settings (
    id integer NOT NULL,
    oidc_enabled boolean DEFAULT false NOT NULL,
    oidc_issuer character varying,
    oidc_client_id character varying,
    oidc_provider_name character varying,
    oidc_scopes json DEFAULT '["openid", "profile", "email"]'::jsonb NOT NULL,
    light_accent_color character varying(20) DEFAULT '#2563eb'::character varying NOT NULL,
    dark_accent_color character varying(20) DEFAULT '#60a5fa'::character varying NOT NULL,
    smtp_host character varying(255),
    smtp_port integer,
    smtp_secure boolean DEFAULT false NOT NULL,
    smtp_reject_unauthorized boolean DEFAULT true NOT NULL,
    smtp_username character varying(255),
    smtp_from_address character varying(255),
    smtp_test_recipient character varying(255),
    ai_enabled boolean DEFAULT false NOT NULL,
    ai_provider character varying(50),
    ai_base_url character varying(1000),
    ai_model character varying(500),
    ai_allow_guild_override boolean DEFAULT true NOT NULL,
    ai_allow_user_override boolean DEFAULT true NOT NULL,
    oidc_role_claim_path character varying(500),
    oidc_client_secret_encrypted character varying,
    smtp_password_encrypted character varying(2000),
    ai_api_key_encrypted character varying(2000)
);

ALTER TABLE ONLY public.app_settings FORCE ROW LEVEL SECURITY;



--
-- Name: app_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.app_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: app_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.app_settings_id_seq OWNED BY public.app_settings.id;


--
-- Name: auto_delegation_jti_blocklist; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.auto_delegation_jti_blocklist (
    jti character varying(64) NOT NULL,
    redeemed_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL
);



--
-- Name: guild_invites; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.guild_invites (
    id integer NOT NULL,
    code character varying(64) NOT NULL,
    guild_id integer NOT NULL,
    created_by_user_id integer,
    expires_at timestamp with time zone,
    max_uses integer,
    uses integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    invitee_email_encrypted character varying(2000)
);

ALTER TABLE ONLY public.guild_invites FORCE ROW LEVEL SECURITY;



--
-- Name: guild_invites_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.guild_invites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: guild_invites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.guild_invites_id_seq OWNED BY public.guild_invites.id;


--
-- Name: guild_memberships; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.guild_memberships (
    guild_id integer NOT NULL,
    user_id integer NOT NULL,
    role public.guild_role DEFAULT 'member'::public.guild_role NOT NULL,
    joined_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    oidc_managed boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY public.guild_memberships FORCE ROW LEVEL SECURITY;



--
-- Name: guilds; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.guilds (
    id integer NOT NULL,
    name character varying NOT NULL,
    description text,
    icon_base64 text,
    created_by_user_id integer,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    max_storage_bytes bigint
);

ALTER TABLE ONLY public.guilds FORCE ROW LEVEL SECURITY;



--
-- Name: guilds_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.guilds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: guilds_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.guilds_id_seq OWNED BY public.guilds.id;


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.notifications (
    id integer NOT NULL,
    user_id integer NOT NULL,
    type character varying(64) NOT NULL,
    data json DEFAULT '{}'::json NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);



--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;


--
-- Name: oidc_claim_mappings; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.oidc_claim_mappings (
    id integer NOT NULL,
    claim_value character varying(500) NOT NULL,
    target_type character varying(20) NOT NULL,
    guild_id integer NOT NULL,
    guild_role character varying(20) DEFAULT 'member'::character varying NOT NULL,
    initiative_id integer,
    initiative_role_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.oidc_claim_mappings FORCE ROW LEVEL SECURITY;



--
-- Name: oidc_claim_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.oidc_claim_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: oidc_claim_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.oidc_claim_mappings_id_seq OWNED BY public.oidc_claim_mappings.id;


--
-- Name: push_tokens; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.push_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    device_token_id integer,
    push_token character varying(512) NOT NULL,
    platform character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);



--
-- Name: push_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.push_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: push_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.push_tokens_id_seq OWNED BY public.push_tokens.id;


--
-- Name: user_tokens; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.user_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token character varying(128) NOT NULL,
    purpose public.user_token_purpose NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    device_name character varying(255)
);



--
-- Name: user_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.user_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: user_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.user_tokens_id_seq OWNED BY public.user_tokens.id;


--
-- Name: user_view_preferences; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.user_view_preferences (
    id integer NOT NULL,
    user_id integer NOT NULL,
    scope_key character varying(128) NOT NULL,
    value json NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.user_view_preferences FORCE ROW LEVEL SECURITY;



--
-- Name: user_view_preferences_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.user_view_preferences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: user_view_preferences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.user_view_preferences_id_seq OWNED BY public.user_view_preferences.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: initiative
--

CREATE TABLE public.users (
    id integer NOT NULL,
    full_name character varying,
    hashed_password character varying NOT NULL,
    role public.user_role DEFAULT 'member'::public.user_role NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    avatar_base64 text,
    avatar_url character varying(2048),
    email_verified boolean DEFAULT true NOT NULL,
    timezone character varying(64) DEFAULT 'UTC'::character varying NOT NULL,
    overdue_notification_time character varying(5) DEFAULT '21:00'::character varying NOT NULL,
    email_initiative_addition boolean DEFAULT true NOT NULL,
    email_task_assignment boolean DEFAULT true NOT NULL,
    email_project_added boolean DEFAULT true NOT NULL,
    email_overdue_tasks boolean DEFAULT true NOT NULL,
    last_overdue_notification_at timestamp with time zone,
    last_task_assignment_digest_at timestamp with time zone,
    week_starts_on integer DEFAULT 0 NOT NULL,
    email_mentions boolean DEFAULT true NOT NULL,
    ai_enabled boolean,
    ai_provider character varying(50),
    ai_base_url character varying(1000),
    ai_model character varying(500),
    color_theme character varying(50) DEFAULT 'kobold'::character varying NOT NULL,
    push_initiative_addition boolean DEFAULT true NOT NULL,
    push_task_assignment boolean DEFAULT true NOT NULL,
    push_project_added boolean DEFAULT true NOT NULL,
    push_overdue_tasks boolean DEFAULT true NOT NULL,
    push_mentions boolean DEFAULT true NOT NULL,
    oidc_refresh_token_encrypted text,
    oidc_last_synced_at timestamp with time zone,
    oidc_sub character varying(255),
    locale character varying(10) DEFAULT 'en'::character varying NOT NULL,
    ai_api_key_encrypted character varying(2000),
    email_hash character varying(64) NOT NULL,
    email_encrypted character varying(2000) NOT NULL,
    token_version integer DEFAULT 1 NOT NULL,
    task_completion_visual_feedback character varying(32) DEFAULT 'none'::character varying NOT NULL,
    task_completion_audio_feedback boolean DEFAULT true NOT NULL,
    task_completion_haptic_feedback boolean DEFAULT true NOT NULL,
    status public.user_status DEFAULT 'active'::public.user_status NOT NULL,
    email_events boolean DEFAULT true NOT NULL,
    push_events boolean DEFAULT true NOT NULL,
    email_event_reminders boolean DEFAULT true NOT NULL,
    push_event_reminders boolean DEFAULT true NOT NULL,
    event_reminder_minutes_before integer DEFAULT 15,
    recent_tabs_limit integer DEFAULT 20 NOT NULL
);

ALTER TABLE ONLY public.users FORCE ROW LEVEL SECURITY;



--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: initiative
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: initiative
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: access_grants id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.access_grants ALTER COLUMN id SET DEFAULT nextval('public.access_grants_id_seq'::regclass);


--
-- Name: app_settings id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.app_settings ALTER COLUMN id SET DEFAULT nextval('public.app_settings_id_seq'::regclass);


--
-- Name: guild_invites id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guild_invites ALTER COLUMN id SET DEFAULT nextval('public.guild_invites_id_seq'::regclass);


--
-- Name: guilds id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guilds ALTER COLUMN id SET DEFAULT nextval('public.guilds_id_seq'::regclass);


--
-- Name: notifications id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);


--
-- Name: oidc_claim_mappings id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.oidc_claim_mappings ALTER COLUMN id SET DEFAULT nextval('public.oidc_claim_mappings_id_seq'::regclass);


--
-- Name: push_tokens id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.push_tokens ALTER COLUMN id SET DEFAULT nextval('public.push_tokens_id_seq'::regclass);


--
-- Name: user_api_keys id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_api_keys ALTER COLUMN id SET DEFAULT nextval('public.admin_api_keys_id_seq'::regclass);


--
-- Name: user_tokens id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_tokens ALTER COLUMN id SET DEFAULT nextval('public.user_tokens_id_seq'::regclass);


--
-- Name: user_view_preferences id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_view_preferences ALTER COLUMN id SET DEFAULT nextval('public.user_view_preferences_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: access_grants access_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_pkey PRIMARY KEY (id);


--
-- Name: user_api_keys admin_api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT admin_api_keys_pkey PRIMARY KEY (id);


--
-- Name: user_api_keys admin_api_keys_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT admin_api_keys_token_hash_key UNIQUE (token_hash);


--
-- Name: app_settings app_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (id);


--
-- Name: auto_delegation_jti_blocklist auto_delegation_jti_blocklist_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.auto_delegation_jti_blocklist
    ADD CONSTRAINT auto_delegation_jti_blocklist_pkey PRIMARY KEY (jti);


--
-- Name: guild_invites guild_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guild_invites
    ADD CONSTRAINT guild_invites_pkey PRIMARY KEY (id);


--
-- Name: guild_memberships guild_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guild_memberships
    ADD CONSTRAINT guild_memberships_pkey PRIMARY KEY (guild_id, user_id);


--
-- Name: guilds guilds_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guilds
    ADD CONSTRAINT guilds_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: oidc_claim_mappings oidc_claim_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.oidc_claim_mappings
    ADD CONSTRAINT oidc_claim_mappings_pkey PRIMARY KEY (id);


--
-- Name: push_tokens push_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.push_tokens
    ADD CONSTRAINT push_tokens_pkey PRIMARY KEY (id);


--
-- Name: user_view_preferences uq_user_view_preferences_user_scope; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_view_preferences
    ADD CONSTRAINT uq_user_view_preferences_user_scope UNIQUE (user_id, scope_key);


--
-- Name: users uq_users_email_hash; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email_hash UNIQUE (email_hash);


--
-- Name: user_tokens user_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_tokens
    ADD CONSTRAINT user_tokens_pkey PRIMARY KEY (id);


--
-- Name: user_view_preferences user_view_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_view_preferences
    ADD CONSTRAINT user_view_preferences_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_guild_memberships_user_guild; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX idx_guild_memberships_user_guild ON public.guild_memberships USING btree (user_id, guild_id);


--
-- Name: ix_access_grants_guild_id; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_access_grants_guild_id ON public.access_grants USING btree (guild_id);


--
-- Name: ix_access_grants_status; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_access_grants_status ON public.access_grants USING btree (status);


--
-- Name: ix_access_grants_user_guild; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_access_grants_user_guild ON public.access_grants USING btree (user_id, guild_id);


--
-- Name: ix_access_grants_user_id; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_access_grants_user_id ON public.access_grants USING btree (user_id);


--
-- Name: ix_admin_api_keys_token_prefix; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_admin_api_keys_token_prefix ON public.user_api_keys USING btree (token_prefix);


--
-- Name: ix_admin_api_keys_user_id; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_admin_api_keys_user_id ON public.user_api_keys USING btree (user_id);


--
-- Name: ix_auto_delegation_jti_blocklist_expires_at; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_auto_delegation_jti_blocklist_expires_at ON public.auto_delegation_jti_blocklist USING btree (expires_at);


--
-- Name: ix_guild_invites_code; Type: INDEX; Schema: public; Owner: initiative
--

CREATE UNIQUE INDEX ix_guild_invites_code ON public.guild_invites USING btree (code);


--
-- Name: ix_notifications_user_read; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_notifications_user_read ON public.notifications USING btree (user_id, read_at);


--
-- Name: ix_push_tokens_push_token; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_push_tokens_push_token ON public.push_tokens USING btree (push_token);


--
-- Name: ix_push_tokens_user_device_token; Type: INDEX; Schema: public; Owner: initiative
--

CREATE UNIQUE INDEX ix_push_tokens_user_device_token ON public.push_tokens USING btree (user_id, push_token);


--
-- Name: ix_push_tokens_user_id; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_push_tokens_user_id ON public.push_tokens USING btree (user_id);


--
-- Name: ix_user_api_keys_guild_id; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_user_api_keys_guild_id ON public.user_api_keys USING btree (guild_id);


--
-- Name: ix_user_tokens_token; Type: INDEX; Schema: public; Owner: initiative
--

CREATE UNIQUE INDEX ix_user_tokens_token ON public.user_tokens USING btree (token);


--
-- Name: ix_user_tokens_user_id; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_user_tokens_user_id ON public.user_tokens USING btree (user_id);


--
-- Name: ix_user_view_preferences_user_id; Type: INDEX; Schema: public; Owner: initiative
--

CREATE INDEX ix_user_view_preferences_user_id ON public.user_view_preferences USING btree (user_id);


--
-- Name: access_grants access_grants_approved_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_approved_by_id_fkey FOREIGN KEY (approved_by_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: access_grants access_grants_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;


--
-- Name: access_grants access_grants_requested_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_requested_by_id_fkey FOREIGN KEY (requested_by_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: access_grants access_grants_revoked_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_revoked_by_id_fkey FOREIGN KEY (revoked_by_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: access_grants access_grants_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_api_keys admin_api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT admin_api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_api_keys fk_user_api_keys_guild_id_guilds; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT fk_user_api_keys_guild_id_guilds FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;


--
-- Name: guild_invites guild_invites_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guild_invites
    ADD CONSTRAINT guild_invites_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: guild_invites guild_invites_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guild_invites
    ADD CONSTRAINT guild_invites_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;


--
-- Name: guild_memberships guild_memberships_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guild_memberships
    ADD CONSTRAINT guild_memberships_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;


--
-- Name: guild_memberships guild_memberships_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guild_memberships
    ADD CONSTRAINT guild_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: guilds guilds_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.guilds
    ADD CONSTRAINT guilds_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: oidc_claim_mappings oidc_claim_mappings_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.oidc_claim_mappings
    ADD CONSTRAINT oidc_claim_mappings_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;


--
-- Name: push_tokens push_tokens_device_token_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.push_tokens
    ADD CONSTRAINT push_tokens_device_token_id_fkey FOREIGN KEY (device_token_id) REFERENCES public.user_tokens(id) ON DELETE CASCADE;


--
-- Name: push_tokens push_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.push_tokens
    ADD CONSTRAINT push_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_tokens user_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_tokens
    ADD CONSTRAINT user_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_view_preferences user_view_preferences_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: initiative
--

ALTER TABLE ONLY public.user_view_preferences
    ADD CONSTRAINT user_view_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: access_grants; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.access_grants ENABLE ROW LEVEL SECURITY;

--
-- Name: access_grants access_grants_admin; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY access_grants_admin ON public.access_grants TO platform_admin, platform_owner USING (true) WITH CHECK (true);


--
-- Name: access_grants access_grants_self; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY access_grants_self ON public.access_grants USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));


--
-- Name: app_settings; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.app_settings ENABLE ROW LEVEL SECURITY;

--
-- Name: app_settings app_settings_owner; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY app_settings_owner ON public.app_settings TO platform_owner USING (true) WITH CHECK (true);


--
-- Name: app_settings app_settings_read; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY app_settings_read ON public.app_settings FOR SELECT USING (true);


--
-- Name: guild_invites guild_delete; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_delete ON public.guild_invites FOR DELETE USING ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));


--
-- Name: guilds guild_delete; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_delete ON public.guilds FOR DELETE USING (((id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));


--
-- Name: guild_invites guild_insert; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_insert ON public.guild_invites FOR INSERT WITH CHECK ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));


--
-- Name: guilds guild_insert; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_insert ON public.guilds FOR INSERT WITH CHECK (((NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer IS NOT NULL));


--
-- Name: guild_invites; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.guild_invites ENABLE ROW LEVEL SECURITY;

--
-- Name: oidc_claim_mappings guild_isolation; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_isolation ON public.oidc_claim_mappings USING ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer)) WITH CHECK ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));


--
-- Name: guild_memberships; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.guild_memberships ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_memberships guild_memberships_delete; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_memberships_delete ON public.guild_memberships FOR DELETE USING ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));


--
-- Name: guild_memberships guild_memberships_insert; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_memberships_insert ON public.guild_memberships FOR INSERT WITH CHECK ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));


--
-- Name: guild_memberships guild_memberships_select; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_memberships_select ON public.guild_memberships FOR SELECT USING (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) OR (user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));


--
-- Name: guild_memberships guild_memberships_update; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_memberships_update ON public.guild_memberships FOR UPDATE USING ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer)) WITH CHECK ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));


--
-- Name: guild_invites guild_select; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_select ON public.guild_invites FOR SELECT USING ((EXISTS ( SELECT 1
   FROM public.guild_memberships
  WHERE ((guild_memberships.guild_id = guild_invites.guild_id) AND (guild_memberships.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)))));


--
-- Name: guilds guild_select; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_select ON public.guilds FOR SELECT USING (((id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) OR (EXISTS ( SELECT 1
   FROM public.guild_memberships
  WHERE ((guild_memberships.guild_id = guilds.id) AND (guild_memberships.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))))));


--
-- Name: guild_invites guild_update; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_update ON public.guild_invites FOR UPDATE USING ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer)) WITH CHECK ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));


--
-- Name: guilds guild_update; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guild_update ON public.guilds FOR UPDATE USING (((id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.current_guild_role'::text, true) = 'admin'::text))) WITH CHECK (((id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));


--
-- Name: guilds; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.guilds ENABLE ROW LEVEL SECURITY;

--
-- Name: guilds guilds_pam_read; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY guilds_pam_read ON public.guilds FOR SELECT USING (((id = (NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.pam_read'::text, true) = 'true'::text)));


--
-- Name: oidc_claim_mappings; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.oidc_claim_mappings ENABLE ROW LEVEL SECURITY;

--
-- Name: user_view_preferences; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.user_view_preferences ENABLE ROW LEVEL SECURITY;

--
-- Name: user_view_preferences user_view_preferences_self_scope; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY user_view_preferences_self_scope ON public.user_view_preferences USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));


--
-- Name: users; Type: ROW SECURITY; Schema: public; Owner: initiative
--

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

--
-- Name: users users_app_floor; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY users_app_floor ON public.users TO app_user USING (true) WITH CHECK (true);


--
-- Name: users users_guild_floor; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY users_guild_floor ON public.users TO app_guild_base USING (true) WITH CHECK (true);


--
-- Name: users users_no_delete; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY users_no_delete ON public.users AS RESTRICTIVE FOR DELETE USING (false);


--
-- Name: users users_platform_manage; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY users_platform_manage ON public.users FOR UPDATE TO platform_moderator, platform_admin, platform_owner USING (true) WITH CHECK (true);


--
-- Name: users users_platform_read; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY users_platform_read ON public.users FOR SELECT TO platform_support, platform_moderator, platform_admin, platform_owner USING (true);


--
-- Name: users users_platform_self; Type: POLICY; Schema: public; Owner: initiative
--

CREATE POLICY users_platform_self ON public.users TO platform_base USING ((id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

GRANT USAGE ON SCHEMA public TO app_guild_base;
GRANT USAGE ON SCHEMA public TO platform_base;


--
-- Name: FUNCTION reorder_guild_memberships(p_user_id integer, p_guild_ids integer[]); Type: ACL; Schema: public; Owner: initiative
--

REVOKE ALL ON FUNCTION public.reorder_guild_memberships(p_user_id integer, p_guild_ids integer[]) FROM PUBLIC;
GRANT ALL ON FUNCTION public.reorder_guild_memberships(p_user_id integer, p_guild_ids integer[]) TO app_user;
GRANT ALL ON FUNCTION public.reorder_guild_memberships(p_user_id integer, p_guild_ids integer[]) TO platform_base;


--
-- Name: TABLE access_grants; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.access_grants TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.access_grants TO platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.access_grants TO app_admin;
GRANT SELECT ON TABLE public.access_grants TO app_user;


--
-- Name: SEQUENCE access_grants_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.access_grants_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.access_grants_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.access_grants_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.access_grants_id_seq TO platform_base;


--
-- Name: TABLE user_api_keys; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_api_keys TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_api_keys TO platform_base;
GRANT SELECT,DELETE ON TABLE public.user_api_keys TO app_admin;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_api_keys TO app_user;


--
-- Name: SEQUENCE admin_api_keys_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.admin_api_keys_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.admin_api_keys_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.admin_api_keys_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.admin_api_keys_id_seq TO platform_base;


--
-- Name: TABLE app_settings; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT ON TABLE public.app_settings TO app_guild_base;
GRANT SELECT ON TABLE public.app_settings TO platform_base;
GRANT INSERT,DELETE,UPDATE ON TABLE public.app_settings TO platform_owner;
GRANT SELECT,INSERT,UPDATE ON TABLE public.app_settings TO app_admin;
GRANT SELECT ON TABLE public.app_settings TO app_user;


--
-- Name: SEQUENCE app_settings_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.app_settings_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.app_settings_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.app_settings_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.app_settings_id_seq TO platform_base;


--
-- Name: TABLE auto_delegation_jti_blocklist; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.auto_delegation_jti_blocklist TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.auto_delegation_jti_blocklist TO platform_base;
GRANT SELECT,INSERT ON TABLE public.auto_delegation_jti_blocklist TO app_admin;
GRANT SELECT,INSERT ON TABLE public.auto_delegation_jti_blocklist TO app_user;


--
-- Name: TABLE guild_invites; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_invites TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_invites TO platform_base;
GRANT SELECT,INSERT,UPDATE ON TABLE public.guild_invites TO app_admin;
GRANT SELECT ON TABLE public.guild_invites TO app_user;


--
-- Name: SEQUENCE guild_invites_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.guild_invites_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.guild_invites_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.guild_invites_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.guild_invites_id_seq TO platform_base;


--
-- Name: TABLE guild_memberships; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_memberships TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_memberships TO platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_memberships TO app_admin;
GRANT SELECT ON TABLE public.guild_memberships TO app_user;


--
-- Name: TABLE guilds; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guilds TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guilds TO platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guilds TO app_admin;
GRANT SELECT ON TABLE public.guilds TO app_user;


--
-- Name: SEQUENCE guilds_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.guilds_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.guilds_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.guilds_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.guilds_id_seq TO platform_base;


--
-- Name: TABLE notifications; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.notifications TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.notifications TO platform_base;
GRANT SELECT,INSERT,DELETE ON TABLE public.notifications TO app_admin;


--
-- Name: SEQUENCE notifications_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.notifications_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.notifications_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.notifications_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.notifications_id_seq TO platform_base;


--
-- Name: TABLE oidc_claim_mappings; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.oidc_claim_mappings TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.oidc_claim_mappings TO platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.oidc_claim_mappings TO app_admin;


--
-- Name: SEQUENCE oidc_claim_mappings_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.oidc_claim_mappings_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.oidc_claim_mappings_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.oidc_claim_mappings_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.oidc_claim_mappings_id_seq TO platform_base;


--
-- Name: TABLE push_tokens; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.push_tokens TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.push_tokens TO platform_base;
GRANT SELECT,INSERT,DELETE ON TABLE public.push_tokens TO app_admin;


--
-- Name: SEQUENCE push_tokens_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.push_tokens_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.push_tokens_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.push_tokens_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.push_tokens_id_seq TO platform_base;


--
-- Name: TABLE user_tokens; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_tokens TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_tokens TO platform_base;
GRANT SELECT,INSERT,DELETE ON TABLE public.user_tokens TO app_admin;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_tokens TO app_user;


--
-- Name: SEQUENCE user_tokens_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.user_tokens_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.user_tokens_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.user_tokens_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.user_tokens_id_seq TO platform_base;


--
-- Name: TABLE user_view_preferences; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_view_preferences TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_view_preferences TO platform_base;


--
-- Name: SEQUENCE user_view_preferences_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.user_view_preferences_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.user_view_preferences_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.user_view_preferences_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.user_view_preferences_id_seq TO platform_base;


--
-- Name: TABLE users; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.users TO app_guild_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.users TO platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.users TO app_admin;
GRANT SELECT,UPDATE ON TABLE public.users TO app_user;


--
-- Name: SEQUENCE users_id_seq; Type: ACL; Schema: public; Owner: initiative
--

GRANT SELECT,USAGE ON SEQUENCE public.users_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.users_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.users_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.users_id_seq TO platform_base;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: initiative
--

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,USAGE ON SEQUENCES TO app_guild_base;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,USAGE ON SEQUENCES TO platform_base;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: initiative
--

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO app_guild_base;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO platform_base;


--
-- PostgreSQL database dump complete
--

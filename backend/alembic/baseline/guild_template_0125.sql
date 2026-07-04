--
-- FROZEN SNAPSHOT - part of the 20260626_0125 baseline migration record.
-- The guild_template schema exactly as the pre-collapse migration chain built
-- it (structure, indexes, constraints, guild_id triggers, initiative RLS
-- policies). Applied once: by the baseline on fresh installs, and by the
-- 20260702_0126 reconciler on pre-squash deployments that skip the baseline.
-- Never regenerate or edit - ongoing guild-schema changes are ordinary
-- migrations (scripts/gen_guild_migration.py), and NEW guilds are provisioned
-- by reflecting the LIVE guild_template, not from any file.
--

--
-- PostgreSQL database dump
--


-- Dumped from database version 17.8 (Debian 17.8-1.pgdg13+1)
-- Dumped by pg_dump version 17.8 (Debian 17.8-1.pgdg13+1)


--
-- Name: guild_template; Type: SCHEMA; Schema: -; Owner: initiative
--

CREATE SCHEMA guild_template;





--
-- Name: calendar_event_attendees; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.calendar_event_attendees (
    calendar_event_id integer NOT NULL,
    user_id integer NOT NULL,
    guild_id integer NOT NULL,
    rsvp_status public.rsvp_status DEFAULT 'pending'::public.rsvp_status NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.calendar_event_attendees FORCE ROW LEVEL SECURITY;



--
-- Name: calendar_event_documents; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.calendar_event_documents (
    calendar_event_id integer NOT NULL,
    document_id integer NOT NULL,
    guild_id integer NOT NULL,
    attached_by_id integer,
    attached_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.calendar_event_documents FORCE ROW LEVEL SECURITY;



--
-- Name: calendar_event_property_values; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.calendar_event_property_values (
    event_id integer NOT NULL,
    property_id integer NOT NULL,
    value_text text,
    value_number numeric,
    value_boolean boolean,
    value_date date,
    value_datetime timestamp with time zone,
    value_user_id integer,
    value_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.calendar_event_property_values FORCE ROW LEVEL SECURITY;



--
-- Name: calendar_event_tags; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.calendar_event_tags (
    calendar_event_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.calendar_event_tags FORCE ROW LEVEL SECURITY;



--
-- Name: calendar_events; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.calendar_events (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    initiative_id integer NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    location character varying(500),
    start_at timestamp with time zone NOT NULL,
    end_at timestamp with time zone NOT NULL,
    all_day boolean DEFAULT false NOT NULL,
    color character varying(32),
    recurrence text,
    created_by_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.calendar_events FORCE ROW LEVEL SECURITY;



--
-- Name: calendar_events_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.calendar_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: calendar_events_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.calendar_events_id_seq OWNED BY guild_template.calendar_events.id;


--
-- Name: comments; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.comments (
    id integer NOT NULL,
    content text NOT NULL,
    author_id integer NOT NULL,
    task_id integer,
    document_id integer,
    parent_comment_id integer,
    created_at timestamp with time zone NOT NULL,
    guild_id integer,
    updated_at timestamp with time zone,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    CONSTRAINT ck_comments_task_or_document CHECK (((task_id IS NULL) <> (document_id IS NULL)))
);

ALTER TABLE ONLY guild_template.comments FORCE ROW LEVEL SECURITY;



--
-- Name: comments_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.comments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: comments_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.comments_id_seq OWNED BY guild_template.comments.id;


--
-- Name: counter_groups; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.counter_groups (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    created_by_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.counter_groups FORCE ROW LEVEL SECURITY;



--
-- Name: counter_groups_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.counter_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: counter_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.counter_groups_id_seq OWNED BY guild_template.counter_groups.id;


--
-- Name: counters; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.counters (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    counter_group_id integer NOT NULL,
    name character varying(255) NOT NULL,
    color character varying(32),
    count numeric(20,10) DEFAULT '0'::numeric NOT NULL,
    min numeric(20,10),
    max numeric(20,10),
    step numeric(20,10) DEFAULT '1'::numeric NOT NULL,
    initial_count numeric(20,10) DEFAULT '0'::numeric NOT NULL,
    view_mode public.counter_view_mode DEFAULT 'number'::public.counter_view_mode NOT NULL,
    "position" numeric(20,10) DEFAULT '0'::numeric NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.counters FORCE ROW LEVEL SECURITY;



--
-- Name: counters_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.counters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: counters_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.counters_id_seq OWNED BY guild_template.counters.id;


--
-- Name: document_file_versions; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.document_file_versions (
    id integer NOT NULL,
    document_id integer NOT NULL,
    guild_id integer,
    version_number integer NOT NULL,
    file_url character varying(512) NOT NULL,
    file_content_type character varying(128),
    file_size bigint,
    original_filename character varying(255),
    uploaded_by_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY guild_template.document_file_versions FORCE ROW LEVEL SECURITY;



--
-- Name: document_file_versions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.document_file_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: document_file_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.document_file_versions_id_seq OWNED BY guild_template.document_file_versions.id;


--
-- Name: document_links; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.document_links (
    source_document_id integer NOT NULL,
    target_document_id integer NOT NULL,
    guild_id integer,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.document_links FORCE ROW LEVEL SECURITY;



--
-- Name: document_property_values; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.document_property_values (
    document_id integer NOT NULL,
    property_id integer NOT NULL,
    value_text text,
    value_number numeric,
    value_boolean boolean,
    value_date date,
    value_datetime timestamp with time zone,
    value_user_id integer,
    value_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.document_property_values FORCE ROW LEVEL SECURITY;



--
-- Name: document_tags; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.document_tags (
    document_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.document_tags FORCE ROW LEVEL SECURITY;



--
-- Name: documents; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.documents (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    title character varying(255) NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by_id integer NOT NULL,
    updated_by_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    featured_image_url character varying(512),
    is_template boolean NOT NULL,
    yjs_state bytea,
    yjs_updated_at timestamp with time zone,
    guild_id integer NOT NULL,
    document_type public.document_type DEFAULT 'native'::public.document_type NOT NULL,
    file_url character varying(512),
    file_content_type character varying(128),
    file_size bigint,
    original_filename character varying(255),
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.documents FORCE ROW LEVEL SECURITY;



--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: documents_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.documents_id_seq OWNED BY guild_template.documents.id;


--
-- Name: event_reminder_dispatches; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.event_reminder_dispatches (
    id integer NOT NULL,
    event_id integer NOT NULL,
    user_id integer NOT NULL,
    event_start_at timestamp with time zone NOT NULL,
    sent_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.event_reminder_dispatches FORCE ROW LEVEL SECURITY;



--
-- Name: event_reminder_dispatches_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.event_reminder_dispatches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: event_reminder_dispatches_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.event_reminder_dispatches_id_seq OWNED BY guild_template.event_reminder_dispatches.id;


--
-- Name: guild_settings; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.guild_settings (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    ai_enabled boolean,
    ai_provider character varying(50),
    ai_base_url character varying(1000),
    ai_model character varying(500),
    ai_allow_user_override boolean,
    ai_api_key_encrypted character varying(2000),
    retention_days integer DEFAULT 90
);



--
-- Name: guild_settings_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.guild_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: guild_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.guild_settings_id_seq OWNED BY guild_template.guild_settings.id;


--
-- Name: initiative_members; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.initiative_members (
    initiative_id integer NOT NULL,
    user_id integer NOT NULL,
    joined_at timestamp with time zone NOT NULL,
    guild_id integer NOT NULL,
    role_id integer,
    oidc_managed boolean DEFAULT false NOT NULL
);



--
-- Name: initiative_role_permissions; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.initiative_role_permissions (
    initiative_role_id integer NOT NULL,
    permission_key character varying(50) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_initiative_role_permissions_permission_key CHECK (((permission_key)::text = ANY (ARRAY[('docs_enabled'::character varying)::text, ('projects_enabled'::character varying)::text, ('create_docs'::character varying)::text, ('create_projects'::character varying)::text, ('queues_enabled'::character varying)::text, ('create_queues'::character varying)::text, ('events_enabled'::character varying)::text, ('create_events'::character varying)::text, ('advanced_tool_enabled'::character varying)::text, ('create_advanced_tool'::character varying)::text, ('counters_enabled'::character varying)::text, ('create_counters'::character varying)::text])))
);



--
-- Name: initiative_roles; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.initiative_roles (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(100) NOT NULL,
    display_name character varying(100) NOT NULL,
    is_builtin boolean DEFAULT false NOT NULL,
    is_manager boolean DEFAULT false NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    override_share_restrictions boolean DEFAULT false NOT NULL
);



--
-- Name: initiative_roles_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.initiative_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: initiative_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.initiative_roles_id_seq OWNED BY guild_template.initiative_roles.id;


--
-- Name: initiatives; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.initiatives (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    color character varying(32),
    is_default boolean NOT NULL,
    guild_id integer NOT NULL,
    queues_enabled boolean DEFAULT false NOT NULL,
    events_enabled boolean DEFAULT false NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    advanced_tool_enabled boolean DEFAULT false NOT NULL,
    counters_enabled boolean DEFAULT false NOT NULL,
    is_archived boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY guild_template.initiatives FORCE ROW LEVEL SECURITY;



--
-- Name: initiatives_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.initiatives_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: initiatives_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.initiatives_id_seq OWNED BY guild_template.initiatives.id;


--
-- Name: project_documents; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.project_documents (
    project_id integer NOT NULL,
    document_id integer NOT NULL,
    attached_by_id integer,
    attached_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    guild_id integer NOT NULL
);

ALTER TABLE ONLY guild_template.project_documents FORCE ROW LEVEL SECURITY;



--
-- Name: project_favorites; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.project_favorites (
    user_id integer NOT NULL,
    project_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    guild_id integer NOT NULL
);

ALTER TABLE ONLY guild_template.project_favorites FORCE ROW LEVEL SECURITY;



--
-- Name: project_orders; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.project_orders (
    user_id integer NOT NULL,
    project_id integer NOT NULL,
    sort_order double precision DEFAULT '0'::double precision NOT NULL,
    guild_id integer NOT NULL
);

ALTER TABLE ONLY guild_template.project_orders FORCE ROW LEVEL SECURITY;



--
-- Name: project_tags; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.project_tags (
    project_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.project_tags FORCE ROW LEVEL SECURITY;



--
-- Name: projects; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.projects (
    id integer NOT NULL,
    name character varying NOT NULL,
    icon character varying(8),
    description text,
    owner_id integer NOT NULL,
    initiative_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_archived boolean NOT NULL,
    is_template boolean NOT NULL,
    archived_at timestamp with time zone,
    pinned_at timestamp with time zone,
    guild_id integer NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.projects FORCE ROW LEVEL SECURITY;



--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.projects_id_seq OWNED BY guild_template.projects.id;


--
-- Name: property_definitions; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.property_definitions (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(100) NOT NULL,
    type public.property_type NOT NULL,
    "position" numeric(20,10) DEFAULT 0 NOT NULL,
    color character varying(9),
    options jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.property_definitions FORCE ROW LEVEL SECURITY;



--
-- Name: property_definitions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.property_definitions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: property_definitions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.property_definitions_id_seq OWNED BY guild_template.property_definitions.id;


--
-- Name: queue_item_documents; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.queue_item_documents (
    queue_item_id integer NOT NULL,
    document_id integer NOT NULL,
    guild_id integer NOT NULL,
    attached_by_id integer,
    attached_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.queue_item_documents FORCE ROW LEVEL SECURITY;



--
-- Name: queue_item_tags; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.queue_item_tags (
    queue_item_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.queue_item_tags FORCE ROW LEVEL SECURITY;



--
-- Name: queue_item_tasks; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.queue_item_tasks (
    queue_item_id integer NOT NULL,
    task_id integer NOT NULL,
    guild_id integer NOT NULL,
    attached_by_id integer,
    attached_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.queue_item_tasks FORCE ROW LEVEL SECURITY;



--
-- Name: queue_items; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.queue_items (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    queue_id integer NOT NULL,
    label character varying(255) NOT NULL,
    "position" numeric(20,10) DEFAULT 0 NOT NULL,
    user_id integer,
    color character varying(32),
    notes text,
    is_visible boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    held_at_round integer
);

ALTER TABLE ONLY guild_template.queue_items FORCE ROW LEVEL SECURITY;



--
-- Name: queue_items_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.queue_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: queue_items_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.queue_items_id_seq OWNED BY guild_template.queue_items.id;


--
-- Name: queues; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.queues (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description character varying,
    created_by_id integer NOT NULL,
    current_round integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    current_item_id integer,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.queues FORCE ROW LEVEL SECURITY;



--
-- Name: queues_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.queues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: queues_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.queues_id_seq OWNED BY guild_template.queues.id;


--
-- Name: recent_views; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.recent_views (
    user_id integer NOT NULL,
    entity_type text NOT NULL,
    entity_id integer NOT NULL,
    guild_id integer,
    last_viewed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_recent_views_entity_type CHECK ((entity_type = ANY (ARRAY['project'::text, 'document'::text, 'queue'::text, 'counter_group'::text])))
);

ALTER TABLE ONLY guild_template.recent_views FORCE ROW LEVEL SECURITY;



--
-- Name: resource_grants; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.resource_grants (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    initiative_id integer NOT NULL,
    resource_type character varying(32) NOT NULL,
    resource_id integer NOT NULL,
    user_id integer,
    role_id integer,
    level character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    all_initiative_members boolean DEFAULT false NOT NULL,
    CONSTRAINT resource_grants_one_grantee CHECK ((((((user_id IS NOT NULL))::integer + ((role_id IS NOT NULL))::integer) + (all_initiative_members)::integer) = 1))
);

ALTER TABLE ONLY guild_template.resource_grants FORCE ROW LEVEL SECURITY;



--
-- Name: resource_grants_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.resource_grants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: resource_grants_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.resource_grants_id_seq OWNED BY guild_template.resource_grants.id;


--
-- Name: subtasks; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.subtasks (
    id integer NOT NULL,
    task_id integer NOT NULL,
    content text NOT NULL,
    is_completed boolean DEFAULT false NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    guild_id integer NOT NULL
);

ALTER TABLE ONLY guild_template.subtasks FORCE ROW LEVEL SECURITY;



--
-- Name: subtasks_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.subtasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: subtasks_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.subtasks_id_seq OWNED BY guild_template.subtasks.id;


--
-- Name: tags; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.tags (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    name character varying(100) NOT NULL,
    color character varying(9) DEFAULT '#6366F1'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.tags FORCE ROW LEVEL SECURITY;



--
-- Name: tags_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: tags_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.tags_id_seq OWNED BY guild_template.tags.id;


--
-- Name: task_assignees; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.task_assignees (
    task_id integer NOT NULL,
    user_id integer NOT NULL,
    guild_id integer NOT NULL
);

ALTER TABLE ONLY guild_template.task_assignees FORCE ROW LEVEL SECURITY;



--
-- Name: task_assignment_digest_items; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.task_assignment_digest_items (
    id integer NOT NULL,
    user_id integer NOT NULL,
    task_id integer NOT NULL,
    project_id integer NOT NULL,
    task_title character varying(255) NOT NULL,
    project_name character varying(255) NOT NULL,
    assigned_by_name character varying(255) NOT NULL,
    assigned_by_id integer,
    created_at timestamp with time zone NOT NULL,
    processed_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.task_assignment_digest_items FORCE ROW LEVEL SECURITY;



--
-- Name: task_assignment_digest_items_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.task_assignment_digest_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: task_assignment_digest_items_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.task_assignment_digest_items_id_seq OWNED BY guild_template.task_assignment_digest_items.id;


--
-- Name: task_property_values; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.task_property_values (
    task_id integer NOT NULL,
    property_id integer NOT NULL,
    value_text text,
    value_number numeric,
    value_boolean boolean,
    value_date date,
    value_datetime timestamp with time zone,
    value_user_id integer,
    value_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.task_property_values FORCE ROW LEVEL SECURITY;



--
-- Name: task_statuses; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.task_statuses (
    id integer NOT NULL,
    project_id integer NOT NULL,
    name character varying(100) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    category public.task_status_category NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    guild_id integer NOT NULL,
    color character varying(9) DEFAULT '#94A3B8'::character varying NOT NULL,
    icon character varying(64) DEFAULT 'circle-dashed'::character varying NOT NULL
);

ALTER TABLE ONLY guild_template.task_statuses FORCE ROW LEVEL SECURITY;



--
-- Name: task_statuses_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.task_statuses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: task_statuses_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.task_statuses_id_seq OWNED BY guild_template.task_statuses.id;


--
-- Name: task_tags; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.task_tags (
    task_id integer NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.task_tags FORCE ROW LEVEL SECURITY;



--
-- Name: tasks; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.tasks (
    id integer NOT NULL,
    project_id integer NOT NULL,
    title character varying NOT NULL,
    description text,
    priority public.task_priority NOT NULL,
    due_date timestamp with time zone,
    "position" numeric(20,10) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    recurrence json,
    recurrence_occurrence_count integer NOT NULL,
    start_date timestamp with time zone,
    task_status_id integer NOT NULL,
    recurrence_strategy character varying(20) NOT NULL,
    is_archived boolean DEFAULT false NOT NULL,
    guild_id integer NOT NULL,
    created_by_id integer,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone
);

ALTER TABLE ONLY guild_template.tasks FORCE ROW LEVEL SECURITY;



--
-- Name: tasks_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.tasks_id_seq OWNED BY guild_template.tasks.id;


--
-- Name: uploads; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.uploads (
    id integer NOT NULL,
    filename character varying NOT NULL,
    guild_id integer NOT NULL,
    uploader_user_id integer NOT NULL,
    size_bytes integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    content_type character varying(255),
    content_hash character varying(64)
);



--
-- Name: uploads_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.uploads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: uploads_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.uploads_id_seq OWNED BY guild_template.uploads.id;


--
-- Name: webhook_subscriptions; Type: TABLE; Schema: guild_template; Owner: initiative
--

CREATE TABLE guild_template.webhook_subscriptions (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    initiative_id integer,
    workflow_id integer,
    created_by_user_id integer NOT NULL,
    target_url character varying(2048) NOT NULL,
    hmac_secret character varying(128) NOT NULL,
    event_types character varying(100)[] NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);



--
-- Name: webhook_subscriptions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: initiative
--

CREATE SEQUENCE guild_template.webhook_subscriptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: webhook_subscriptions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: initiative
--

ALTER SEQUENCE guild_template.webhook_subscriptions_id_seq OWNED BY guild_template.webhook_subscriptions.id;


--
-- Name: calendar_events id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_events ALTER COLUMN id SET DEFAULT nextval('guild_template.calendar_events_id_seq'::regclass);


--
-- Name: comments id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.comments ALTER COLUMN id SET DEFAULT nextval('guild_template.comments_id_seq'::regclass);


--
-- Name: counter_groups id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.counter_groups ALTER COLUMN id SET DEFAULT nextval('guild_template.counter_groups_id_seq'::regclass);


--
-- Name: counters id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.counters ALTER COLUMN id SET DEFAULT nextval('guild_template.counters_id_seq'::regclass);


--
-- Name: document_file_versions id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_file_versions ALTER COLUMN id SET DEFAULT nextval('guild_template.document_file_versions_id_seq'::regclass);


--
-- Name: documents id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.documents ALTER COLUMN id SET DEFAULT nextval('guild_template.documents_id_seq'::regclass);


--
-- Name: event_reminder_dispatches id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches ALTER COLUMN id SET DEFAULT nextval('guild_template.event_reminder_dispatches_id_seq'::regclass);


--
-- Name: guild_settings id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.guild_settings ALTER COLUMN id SET DEFAULT nextval('guild_template.guild_settings_id_seq'::regclass);


--
-- Name: initiative_roles id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_roles ALTER COLUMN id SET DEFAULT nextval('guild_template.initiative_roles_id_seq'::regclass);


--
-- Name: initiatives id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiatives ALTER COLUMN id SET DEFAULT nextval('guild_template.initiatives_id_seq'::regclass);


--
-- Name: projects id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.projects ALTER COLUMN id SET DEFAULT nextval('guild_template.projects_id_seq'::regclass);


--
-- Name: property_definitions id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.property_definitions ALTER COLUMN id SET DEFAULT nextval('guild_template.property_definitions_id_seq'::regclass);


--
-- Name: queue_items id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_items ALTER COLUMN id SET DEFAULT nextval('guild_template.queue_items_id_seq'::regclass);


--
-- Name: queues id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queues ALTER COLUMN id SET DEFAULT nextval('guild_template.queues_id_seq'::regclass);


--
-- Name: resource_grants id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.resource_grants ALTER COLUMN id SET DEFAULT nextval('guild_template.resource_grants_id_seq'::regclass);


--
-- Name: subtasks id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.subtasks ALTER COLUMN id SET DEFAULT nextval('guild_template.subtasks_id_seq'::regclass);


--
-- Name: tags id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.tags ALTER COLUMN id SET DEFAULT nextval('guild_template.tags_id_seq'::regclass);


--
-- Name: task_assignment_digest_items id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items ALTER COLUMN id SET DEFAULT nextval('guild_template.task_assignment_digest_items_id_seq'::regclass);


--
-- Name: task_statuses id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_statuses ALTER COLUMN id SET DEFAULT nextval('guild_template.task_statuses_id_seq'::regclass);


--
-- Name: tasks id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.tasks ALTER COLUMN id SET DEFAULT nextval('guild_template.tasks_id_seq'::regclass);


--
-- Name: uploads id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.uploads ALTER COLUMN id SET DEFAULT nextval('guild_template.uploads_id_seq'::regclass);


--
-- Name: webhook_subscriptions id; Type: DEFAULT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.webhook_subscriptions ALTER COLUMN id SET DEFAULT nextval('guild_template.webhook_subscriptions_id_seq'::regclass);


--
-- Name: calendar_event_attendees calendar_event_attendees_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_attendees
    ADD CONSTRAINT calendar_event_attendees_pkey PRIMARY KEY (calendar_event_id, user_id);


--
-- Name: calendar_event_documents calendar_event_documents_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_documents
    ADD CONSTRAINT calendar_event_documents_pkey PRIMARY KEY (calendar_event_id, document_id);


--
-- Name: calendar_event_property_values calendar_event_property_values_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_property_values
    ADD CONSTRAINT calendar_event_property_values_pkey PRIMARY KEY (event_id, property_id);


--
-- Name: calendar_event_tags calendar_event_tags_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_tags
    ADD CONSTRAINT calendar_event_tags_pkey PRIMARY KEY (calendar_event_id, tag_id);


--
-- Name: calendar_events calendar_events_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_events
    ADD CONSTRAINT calendar_events_pkey PRIMARY KEY (id);


--
-- Name: comments comments_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_pkey PRIMARY KEY (id);


--
-- Name: counter_groups counter_groups_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.counter_groups
    ADD CONSTRAINT counter_groups_pkey PRIMARY KEY (id);


--
-- Name: counters counters_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.counters
    ADD CONSTRAINT counters_pkey PRIMARY KEY (id);


--
-- Name: document_file_versions document_file_versions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_file_versions
    ADD CONSTRAINT document_file_versions_pkey PRIMARY KEY (id);


--
-- Name: document_links document_links_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_links
    ADD CONSTRAINT document_links_pkey PRIMARY KEY (source_document_id, target_document_id);


--
-- Name: document_property_values document_property_values_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_property_values
    ADD CONSTRAINT document_property_values_pkey PRIMARY KEY (document_id, property_id);


--
-- Name: document_tags document_tags_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_tags
    ADD CONSTRAINT document_tags_pkey PRIMARY KEY (document_id, tag_id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: event_reminder_dispatches event_reminder_dispatches_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches
    ADD CONSTRAINT event_reminder_dispatches_pkey PRIMARY KEY (id);


--
-- Name: guild_settings guild_settings_guild_id_key; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.guild_settings
    ADD CONSTRAINT guild_settings_guild_id_key UNIQUE (guild_id);


--
-- Name: guild_settings guild_settings_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.guild_settings
    ADD CONSTRAINT guild_settings_pkey PRIMARY KEY (id);


--
-- Name: initiative_role_permissions initiative_role_permissions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_role_permissions
    ADD CONSTRAINT initiative_role_permissions_pkey PRIMARY KEY (initiative_role_id, permission_key);


--
-- Name: initiative_roles initiative_roles_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_roles
    ADD CONSTRAINT initiative_roles_pkey PRIMARY KEY (id);


--
-- Name: project_documents project_documents_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_documents
    ADD CONSTRAINT project_documents_pkey PRIMARY KEY (project_id, document_id);


--
-- Name: project_favorites project_favorites_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_favorites
    ADD CONSTRAINT project_favorites_pkey PRIMARY KEY (user_id, project_id);


--
-- Name: project_orders project_orders_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_orders
    ADD CONSTRAINT project_orders_pkey PRIMARY KEY (user_id, project_id);


--
-- Name: project_tags project_tags_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_tags
    ADD CONSTRAINT project_tags_pkey PRIMARY KEY (project_id, tag_id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: property_definitions property_definitions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.property_definitions
    ADD CONSTRAINT property_definitions_pkey PRIMARY KEY (id);


--
-- Name: queue_item_documents queue_item_documents_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_documents
    ADD CONSTRAINT queue_item_documents_pkey PRIMARY KEY (queue_item_id, document_id);


--
-- Name: queue_item_tags queue_item_tags_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_tags
    ADD CONSTRAINT queue_item_tags_pkey PRIMARY KEY (queue_item_id, tag_id);


--
-- Name: queue_item_tasks queue_item_tasks_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_tasks
    ADD CONSTRAINT queue_item_tasks_pkey PRIMARY KEY (queue_item_id, task_id);


--
-- Name: queue_items queue_items_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_items
    ADD CONSTRAINT queue_items_pkey PRIMARY KEY (id);


--
-- Name: queues queues_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queues
    ADD CONSTRAINT queues_pkey PRIMARY KEY (id);


--
-- Name: recent_views recent_views_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.recent_views
    ADD CONSTRAINT recent_views_pkey PRIMARY KEY (user_id, entity_type, entity_id);


--
-- Name: resource_grants resource_grants_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_pkey PRIMARY KEY (id);


--
-- Name: resource_grants resource_grants_unique_grantee; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_unique_grantee UNIQUE NULLS NOT DISTINCT (resource_type, resource_id, user_id, role_id);


--
-- Name: subtasks subtasks_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.subtasks
    ADD CONSTRAINT subtasks_pkey PRIMARY KEY (id);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);


--
-- Name: task_assignees task_assignees_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_assignees
    ADD CONSTRAINT task_assignees_pkey PRIMARY KEY (task_id, user_id);


--
-- Name: task_assignment_digest_items task_assignment_digest_items_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items
    ADD CONSTRAINT task_assignment_digest_items_pkey PRIMARY KEY (id);


--
-- Name: task_property_values task_property_values_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_property_values
    ADD CONSTRAINT task_property_values_pkey PRIMARY KEY (task_id, property_id);


--
-- Name: task_statuses task_statuses_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_statuses
    ADD CONSTRAINT task_statuses_pkey PRIMARY KEY (id);


--
-- Name: task_tags task_tags_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_tags
    ADD CONSTRAINT task_tags_pkey PRIMARY KEY (task_id, tag_id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: initiative_members team_members_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_members
    ADD CONSTRAINT team_members_pkey PRIMARY KEY (initiative_id, user_id);


--
-- Name: initiatives teams_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiatives
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);


--
-- Name: uploads uploads_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.uploads
    ADD CONSTRAINT uploads_pkey PRIMARY KEY (id);


--
-- Name: document_file_versions uq_dfv_document_version; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_file_versions
    ADD CONSTRAINT uq_dfv_document_version UNIQUE (document_id, version_number);


--
-- Name: event_reminder_dispatches uq_event_reminder_dispatch; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches
    ADD CONSTRAINT uq_event_reminder_dispatch UNIQUE (event_id, user_id, event_start_at);


--
-- Name: initiative_roles uq_initiative_role_name; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_roles
    ADD CONSTRAINT uq_initiative_role_name UNIQUE (initiative_id, name);


--
-- Name: webhook_subscriptions webhook_subscriptions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: idx_documents_updated_at; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX idx_documents_updated_at ON guild_template.documents USING btree (updated_at);


--
-- Name: idx_task_assignment_digest_items_unprocessed; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX idx_task_assignment_digest_items_unprocessed ON guild_template.task_assignment_digest_items USING btree (processed_at) WHERE (processed_at IS NULL);


--
-- Name: idx_tasks_due_date_status; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX idx_tasks_due_date_status ON guild_template.tasks USING btree (due_date, task_status_id) WHERE (due_date IS NOT NULL);


--
-- Name: idx_tasks_project_archived; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX idx_tasks_project_archived ON guild_template.tasks USING btree (project_id, is_archived);


--
-- Name: idx_tasks_updated_at; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX idx_tasks_updated_at ON guild_template.tasks USING btree (updated_at);


--
-- Name: ix_calendar_event_attendees_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_attendees_user_id ON guild_template.calendar_event_attendees USING btree (user_id);


--
-- Name: ix_calendar_event_property_values_property_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_property_values_property_id ON guild_template.calendar_event_property_values USING btree (property_id);


--
-- Name: ix_calendar_event_property_values_property_json_gin; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_property_values_property_json_gin ON guild_template.calendar_event_property_values USING gin (value_json jsonb_path_ops) WHERE (value_json IS NOT NULL);


--
-- Name: ix_calendar_event_property_values_property_value_date; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_property_values_property_value_date ON guild_template.calendar_event_property_values USING btree (property_id, value_date) WHERE (value_date IS NOT NULL);


--
-- Name: ix_calendar_event_property_values_property_value_datetime; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_property_values_property_value_datetime ON guild_template.calendar_event_property_values USING btree (property_id, value_datetime) WHERE (value_datetime IS NOT NULL);


--
-- Name: ix_calendar_event_property_values_property_value_number; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_property_values_property_value_number ON guild_template.calendar_event_property_values USING btree (property_id, value_number) WHERE (value_number IS NOT NULL);


--
-- Name: ix_calendar_event_property_values_property_value_text; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_property_values_property_value_text ON guild_template.calendar_event_property_values USING btree (property_id, value_text) WHERE (value_text IS NOT NULL);


--
-- Name: ix_calendar_event_property_values_property_value_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_property_values_property_value_user_id ON guild_template.calendar_event_property_values USING btree (property_id, value_user_id) WHERE (value_user_id IS NOT NULL);


--
-- Name: ix_calendar_event_tags_tag_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_event_tags_tag_id ON guild_template.calendar_event_tags USING btree (tag_id);


--
-- Name: ix_calendar_events_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_events_active ON guild_template.calendar_events USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_calendar_events_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_events_guild_id ON guild_template.calendar_events USING btree (guild_id);


--
-- Name: ix_calendar_events_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_events_initiative_id ON guild_template.calendar_events USING btree (initiative_id);


--
-- Name: ix_calendar_events_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_events_purge ON guild_template.calendar_events USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_calendar_events_start_at; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_calendar_events_start_at ON guild_template.calendar_events USING btree (start_at);


--
-- Name: ix_comments_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_comments_active ON guild_template.comments USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_comments_author_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_comments_author_id ON guild_template.comments USING btree (author_id);


--
-- Name: ix_comments_created_at; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_comments_created_at ON guild_template.comments USING btree (created_at);


--
-- Name: ix_comments_document_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_comments_document_id ON guild_template.comments USING btree (document_id);


--
-- Name: ix_comments_parent_comment_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_comments_parent_comment_id ON guild_template.comments USING btree (parent_comment_id);


--
-- Name: ix_comments_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_comments_purge ON guild_template.comments USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_comments_task_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_comments_task_id ON guild_template.comments USING btree (task_id);


--
-- Name: ix_counter_groups_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_counter_groups_guild_id ON guild_template.counter_groups USING btree (guild_id);


--
-- Name: ix_counter_groups_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_counter_groups_initiative_id ON guild_template.counter_groups USING btree (initiative_id);


--
-- Name: ix_counters_counter_group_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_counters_counter_group_id ON guild_template.counters USING btree (counter_group_id);


--
-- Name: ix_counters_group_position; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_counters_group_position ON guild_template.counters USING btree (counter_group_id, "position");


--
-- Name: ix_counters_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_counters_guild_id ON guild_template.counters USING btree (guild_id);


--
-- Name: ix_document_file_versions_document_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_file_versions_document_id ON guild_template.document_file_versions USING btree (document_id);


--
-- Name: ix_document_links_target_document_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_links_target_document_id ON guild_template.document_links USING btree (target_document_id);


--
-- Name: ix_document_property_values_property_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_property_values_property_id ON guild_template.document_property_values USING btree (property_id);


--
-- Name: ix_document_property_values_property_json_gin; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_property_values_property_json_gin ON guild_template.document_property_values USING gin (value_json jsonb_path_ops) WHERE (value_json IS NOT NULL);


--
-- Name: ix_document_property_values_property_value_date; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_property_values_property_value_date ON guild_template.document_property_values USING btree (property_id, value_date) WHERE (value_date IS NOT NULL);


--
-- Name: ix_document_property_values_property_value_datetime; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_property_values_property_value_datetime ON guild_template.document_property_values USING btree (property_id, value_datetime) WHERE (value_datetime IS NOT NULL);


--
-- Name: ix_document_property_values_property_value_number; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_property_values_property_value_number ON guild_template.document_property_values USING btree (property_id, value_number) WHERE (value_number IS NOT NULL);


--
-- Name: ix_document_property_values_property_value_text; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_property_values_property_value_text ON guild_template.document_property_values USING btree (property_id, value_text) WHERE (value_text IS NOT NULL);


--
-- Name: ix_document_property_values_property_value_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_property_values_property_value_user_id ON guild_template.document_property_values USING btree (property_id, value_user_id) WHERE (value_user_id IS NOT NULL);


--
-- Name: ix_document_tags_tag_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_document_tags_tag_id ON guild_template.document_tags USING btree (tag_id);


--
-- Name: ix_documents_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_documents_active ON guild_template.documents USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_documents_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_documents_guild_id ON guild_template.documents USING btree (guild_id);


--
-- Name: ix_documents_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_documents_initiative_id ON guild_template.documents USING btree (initiative_id);


--
-- Name: ix_documents_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_documents_purge ON guild_template.documents USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_documents_title; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_documents_title ON guild_template.documents USING btree (title);


--
-- Name: ix_event_reminder_dispatches_event_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_event_reminder_dispatches_event_id ON guild_template.event_reminder_dispatches USING btree (event_id);


--
-- Name: ix_event_reminder_dispatches_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_event_reminder_dispatches_user_id ON guild_template.event_reminder_dispatches USING btree (user_id);


--
-- Name: ix_initiative_members_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiative_members_guild_id ON guild_template.initiative_members USING btree (guild_id);


--
-- Name: ix_initiative_members_role_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiative_members_role_id ON guild_template.initiative_members USING btree (role_id);


--
-- Name: ix_initiative_members_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiative_members_user_id ON guild_template.initiative_members USING btree (user_id);


--
-- Name: ix_initiative_roles_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiative_roles_initiative_id ON guild_template.initiative_roles USING btree (initiative_id);


--
-- Name: ix_initiatives_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiatives_active ON guild_template.initiatives USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_initiatives_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiatives_guild_id ON guild_template.initiatives USING btree (guild_id);


--
-- Name: ix_initiatives_name; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiatives_name ON guild_template.initiatives USING btree (name);


--
-- Name: ix_initiatives_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_initiatives_purge ON guild_template.initiatives USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_project_documents_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_project_documents_guild_id ON guild_template.project_documents USING btree (guild_id);


--
-- Name: ix_project_favorites_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_project_favorites_guild_id ON guild_template.project_favorites USING btree (guild_id);


--
-- Name: ix_project_favorites_project_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_project_favorites_project_id ON guild_template.project_favorites USING btree (project_id);


--
-- Name: ix_project_orders_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_project_orders_guild_id ON guild_template.project_orders USING btree (guild_id);


--
-- Name: ix_project_tags_tag_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_project_tags_tag_id ON guild_template.project_tags USING btree (tag_id);


--
-- Name: ix_projects_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_projects_active ON guild_template.projects USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_projects_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_projects_guild_id ON guild_template.projects USING btree (guild_id);


--
-- Name: ix_projects_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_projects_initiative_id ON guild_template.projects USING btree (initiative_id);


--
-- Name: ix_projects_name; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_projects_name ON guild_template.projects USING btree (name);


--
-- Name: ix_projects_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_projects_purge ON guild_template.projects USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_property_definitions_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_property_definitions_initiative_id ON guild_template.property_definitions USING btree (initiative_id);


--
-- Name: ix_property_definitions_initiative_lower_name; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE UNIQUE INDEX ix_property_definitions_initiative_lower_name ON guild_template.property_definitions USING btree (initiative_id, lower((name)::text));


--
-- Name: ix_queue_item_tags_tag_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queue_item_tags_tag_id ON guild_template.queue_item_tags USING btree (tag_id);


--
-- Name: ix_queue_items_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queue_items_active ON guild_template.queue_items USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_queue_items_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queue_items_guild_id ON guild_template.queue_items USING btree (guild_id);


--
-- Name: ix_queue_items_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queue_items_purge ON guild_template.queue_items USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_queue_items_queue_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queue_items_queue_id ON guild_template.queue_items USING btree (queue_id);


--
-- Name: ix_queues_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queues_active ON guild_template.queues USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_queues_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queues_guild_id ON guild_template.queues USING btree (guild_id);


--
-- Name: ix_queues_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queues_initiative_id ON guild_template.queues USING btree (initiative_id);


--
-- Name: ix_queues_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_queues_purge ON guild_template.queues USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_recent_views_entity; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_recent_views_entity ON guild_template.recent_views USING btree (entity_type, entity_id);


--
-- Name: ix_recent_views_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_recent_views_guild_id ON guild_template.recent_views USING btree (guild_id);


--
-- Name: ix_recent_views_user_last_viewed_at; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_recent_views_user_last_viewed_at ON guild_template.recent_views USING btree (user_id, last_viewed_at DESC);


--
-- Name: ix_resource_grants_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_resource_grants_guild_id ON guild_template.resource_grants USING btree (guild_id);


--
-- Name: ix_resource_grants_initiative_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_resource_grants_initiative_id ON guild_template.resource_grants USING btree (initiative_id);


--
-- Name: ix_resource_grants_resource; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_resource_grants_resource ON guild_template.resource_grants USING btree (resource_type, resource_id);


--
-- Name: ix_resource_grants_role; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_resource_grants_role ON guild_template.resource_grants USING btree (role_id, resource_type) WHERE (role_id IS NOT NULL);


--
-- Name: ix_resource_grants_user; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_resource_grants_user ON guild_template.resource_grants USING btree (user_id, resource_type) WHERE (user_id IS NOT NULL);


--
-- Name: ix_subtasks_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_subtasks_guild_id ON guild_template.subtasks USING btree (guild_id);


--
-- Name: ix_subtasks_task_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_subtasks_task_id ON guild_template.subtasks USING btree (task_id);


--
-- Name: ix_tags_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_tags_active ON guild_template.tags USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_tags_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_tags_guild_id ON guild_template.tags USING btree (guild_id);


--
-- Name: ix_tags_guild_name_unique; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE UNIQUE INDEX ix_tags_guild_name_unique ON guild_template.tags USING btree (guild_id, lower((name)::text));


--
-- Name: ix_tags_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_tags_purge ON guild_template.tags USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_task_assignees_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_assignees_guild_id ON guild_template.task_assignees USING btree (guild_id);


--
-- Name: ix_task_assignees_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_assignees_user_id ON guild_template.task_assignees USING btree (user_id);


--
-- Name: ix_task_assignment_digest_items_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_assignment_digest_items_user_id ON guild_template.task_assignment_digest_items USING btree (user_id);


--
-- Name: ix_task_property_values_property_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_property_values_property_id ON guild_template.task_property_values USING btree (property_id);


--
-- Name: ix_task_property_values_property_json_gin; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_property_values_property_json_gin ON guild_template.task_property_values USING gin (value_json jsonb_path_ops) WHERE (value_json IS NOT NULL);


--
-- Name: ix_task_property_values_property_value_date; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_property_values_property_value_date ON guild_template.task_property_values USING btree (property_id, value_date) WHERE (value_date IS NOT NULL);


--
-- Name: ix_task_property_values_property_value_datetime; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_property_values_property_value_datetime ON guild_template.task_property_values USING btree (property_id, value_datetime) WHERE (value_datetime IS NOT NULL);


--
-- Name: ix_task_property_values_property_value_number; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_property_values_property_value_number ON guild_template.task_property_values USING btree (property_id, value_number) WHERE (value_number IS NOT NULL);


--
-- Name: ix_task_property_values_property_value_text; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_property_values_property_value_text ON guild_template.task_property_values USING btree (property_id, value_text) WHERE (value_text IS NOT NULL);


--
-- Name: ix_task_property_values_property_value_user_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_property_values_property_value_user_id ON guild_template.task_property_values USING btree (property_id, value_user_id) WHERE (value_user_id IS NOT NULL);


--
-- Name: ix_task_statuses_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_statuses_guild_id ON guild_template.task_statuses USING btree (guild_id);


--
-- Name: ix_task_statuses_project_position; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_statuses_project_position ON guild_template.task_statuses USING btree (project_id, "position");


--
-- Name: ix_task_tags_tag_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_task_tags_tag_id ON guild_template.task_tags USING btree (tag_id);


--
-- Name: ix_tasks_active; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_tasks_active ON guild_template.tasks USING btree (deleted_at) WHERE (deleted_at IS NULL);


--
-- Name: ix_tasks_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_tasks_guild_id ON guild_template.tasks USING btree (guild_id);


--
-- Name: ix_tasks_project_id_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_tasks_project_id_id ON guild_template.tasks USING btree (project_id, id);


--
-- Name: ix_tasks_purge; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_tasks_purge ON guild_template.tasks USING btree (purge_at) WHERE (purge_at IS NOT NULL);


--
-- Name: ix_uploads_filename; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE UNIQUE INDEX ix_uploads_filename ON guild_template.uploads USING btree (filename);


--
-- Name: ix_uploads_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_uploads_guild_id ON guild_template.uploads USING btree (guild_id);


--
-- Name: ix_webhook_subscriptions_dispatch; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_webhook_subscriptions_dispatch ON guild_template.webhook_subscriptions USING btree (guild_id, initiative_id) WHERE (active = true);


--
-- Name: ix_webhook_subscriptions_guild_id; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE INDEX ix_webhook_subscriptions_guild_id ON guild_template.webhook_subscriptions USING btree (guild_id);


--
-- Name: uq_initiatives_guild_default; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE UNIQUE INDEX uq_initiatives_guild_default ON guild_template.initiatives USING btree (guild_id) WHERE is_default;


--
-- Name: uq_initiatives_guild_name; Type: INDEX; Schema: guild_template; Owner: initiative
--

CREATE UNIQUE INDEX uq_initiatives_guild_name ON guild_template.initiatives USING btree (guild_id, lower((name)::text));


--
-- Name: comments tr_comments_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_comments_set_guild_id BEFORE INSERT OR UPDATE OF task_id, document_id ON guild_template.comments FOR EACH ROW EXECUTE FUNCTION public.fn_comments_set_guild_id();


--
-- Name: documents tr_documents_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_documents_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON guild_template.documents FOR EACH ROW EXECUTE FUNCTION public.fn_documents_set_guild_id();


--
-- Name: initiative_members tr_initiative_members_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_initiative_members_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON guild_template.initiative_members FOR EACH ROW EXECUTE FUNCTION public.fn_initiative_members_set_guild_id();


--
-- Name: project_documents tr_project_documents_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_project_documents_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON guild_template.project_documents FOR EACH ROW EXECUTE FUNCTION public.fn_project_documents_set_guild_id();


--
-- Name: project_favorites tr_project_favorites_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_project_favorites_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON guild_template.project_favorites FOR EACH ROW EXECUTE FUNCTION public.fn_project_favorites_set_guild_id();


--
-- Name: project_orders tr_project_orders_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_project_orders_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON guild_template.project_orders FOR EACH ROW EXECUTE FUNCTION public.fn_project_orders_set_guild_id();


--
-- Name: projects tr_projects_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_projects_set_guild_id BEFORE INSERT OR UPDATE OF initiative_id ON guild_template.projects FOR EACH ROW EXECUTE FUNCTION public.fn_projects_set_guild_id();


--
-- Name: recent_views tr_recent_views_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_recent_views_set_guild_id BEFORE INSERT OR UPDATE OF entity_type, entity_id ON guild_template.recent_views FOR EACH ROW EXECUTE FUNCTION public.fn_recent_views_set_guild_id();


--
-- Name: subtasks tr_subtasks_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_subtasks_set_guild_id BEFORE INSERT OR UPDATE OF task_id ON guild_template.subtasks FOR EACH ROW EXECUTE FUNCTION public.fn_subtasks_set_guild_id();


--
-- Name: task_assignees tr_task_assignees_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_task_assignees_set_guild_id BEFORE INSERT OR UPDATE OF task_id ON guild_template.task_assignees FOR EACH ROW EXECUTE FUNCTION public.fn_task_assignees_set_guild_id();


--
-- Name: task_statuses tr_task_statuses_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_task_statuses_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON guild_template.task_statuses FOR EACH ROW EXECUTE FUNCTION public.fn_task_statuses_set_guild_id();


--
-- Name: tasks tr_tasks_set_guild_id; Type: TRIGGER; Schema: guild_template; Owner: initiative
--

CREATE TRIGGER tr_tasks_set_guild_id BEFORE INSERT OR UPDATE OF project_id ON guild_template.tasks FOR EACH ROW EXECUTE FUNCTION public.fn_tasks_set_guild_id();


--
-- Name: calendar_event_attendees calendar_event_attendees_calendar_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_attendees
    ADD CONSTRAINT calendar_event_attendees_calendar_event_id_fkey FOREIGN KEY (calendar_event_id) REFERENCES guild_template.calendar_events(id) ON DELETE CASCADE;


--
-- Name: calendar_event_documents calendar_event_documents_calendar_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_documents
    ADD CONSTRAINT calendar_event_documents_calendar_event_id_fkey FOREIGN KEY (calendar_event_id) REFERENCES guild_template.calendar_events(id);


--
-- Name: calendar_event_documents calendar_event_documents_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_documents
    ADD CONSTRAINT calendar_event_documents_document_id_fkey FOREIGN KEY (document_id) REFERENCES guild_template.documents(id);


--
-- Name: calendar_event_property_values calendar_event_property_values_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_property_values
    ADD CONSTRAINT calendar_event_property_values_event_id_fkey FOREIGN KEY (event_id) REFERENCES guild_template.calendar_events(id) ON DELETE CASCADE;


--
-- Name: calendar_event_property_values calendar_event_property_values_property_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_property_values
    ADD CONSTRAINT calendar_event_property_values_property_id_fkey FOREIGN KEY (property_id) REFERENCES guild_template.property_definitions(id) ON DELETE CASCADE;


--
-- Name: calendar_event_tags calendar_event_tags_calendar_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_tags
    ADD CONSTRAINT calendar_event_tags_calendar_event_id_fkey FOREIGN KEY (calendar_event_id) REFERENCES guild_template.calendar_events(id);


--
-- Name: calendar_event_tags calendar_event_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_event_tags
    ADD CONSTRAINT calendar_event_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES guild_template.tags(id);


--
-- Name: calendar_events calendar_events_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.calendar_events
    ADD CONSTRAINT calendar_events_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);


--
-- Name: comments comments_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_document_id_fkey FOREIGN KEY (document_id) REFERENCES guild_template.documents(id) ON DELETE CASCADE;


--
-- Name: comments comments_parent_comment_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_parent_comment_id_fkey FOREIGN KEY (parent_comment_id) REFERENCES guild_template.comments(id) ON DELETE CASCADE;


--
-- Name: comments comments_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;


--
-- Name: counter_groups counter_groups_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.counter_groups
    ADD CONSTRAINT counter_groups_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);


--
-- Name: counters counters_counter_group_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.counters
    ADD CONSTRAINT counters_counter_group_id_fkey FOREIGN KEY (counter_group_id) REFERENCES guild_template.counter_groups(id) ON DELETE CASCADE;


--
-- Name: document_file_versions document_file_versions_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_file_versions
    ADD CONSTRAINT document_file_versions_document_id_fkey FOREIGN KEY (document_id) REFERENCES guild_template.documents(id) ON DELETE CASCADE;


--
-- Name: document_links document_links_source_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_links
    ADD CONSTRAINT document_links_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES guild_template.documents(id) ON DELETE CASCADE;


--
-- Name: document_links document_links_target_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_links
    ADD CONSTRAINT document_links_target_document_id_fkey FOREIGN KEY (target_document_id) REFERENCES guild_template.documents(id) ON DELETE CASCADE;


--
-- Name: document_property_values document_property_values_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_property_values
    ADD CONSTRAINT document_property_values_document_id_fkey FOREIGN KEY (document_id) REFERENCES guild_template.documents(id) ON DELETE CASCADE;


--
-- Name: document_property_values document_property_values_property_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_property_values
    ADD CONSTRAINT document_property_values_property_id_fkey FOREIGN KEY (property_id) REFERENCES guild_template.property_definitions(id) ON DELETE CASCADE;


--
-- Name: document_tags document_tags_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_tags
    ADD CONSTRAINT document_tags_document_id_fkey FOREIGN KEY (document_id) REFERENCES guild_template.documents(id) ON DELETE CASCADE;


--
-- Name: document_tags document_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.document_tags
    ADD CONSTRAINT document_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES guild_template.tags(id) ON DELETE CASCADE;


--
-- Name: documents documents_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.documents
    ADD CONSTRAINT documents_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;


--
-- Name: event_reminder_dispatches event_reminder_dispatches_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches
    ADD CONSTRAINT event_reminder_dispatches_event_id_fkey FOREIGN KEY (event_id) REFERENCES guild_template.calendar_events(id) ON DELETE CASCADE;


--
-- Name: queues fk_queues_current_item_id; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queues
    ADD CONSTRAINT fk_queues_current_item_id FOREIGN KEY (current_item_id) REFERENCES guild_template.queue_items(id) ON DELETE SET NULL;


--
-- Name: subtasks fk_subtasks_task_id; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.subtasks
    ADD CONSTRAINT fk_subtasks_task_id FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;


--
-- Name: tasks fk_tasks_task_status_id; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.tasks
    ADD CONSTRAINT fk_tasks_task_status_id FOREIGN KEY (task_status_id) REFERENCES guild_template.task_statuses(id) ON DELETE RESTRICT;


--
-- Name: initiative_members initiative_members_role_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_members
    ADD CONSTRAINT initiative_members_role_id_fkey FOREIGN KEY (role_id) REFERENCES guild_template.initiative_roles(id) ON DELETE SET NULL;


--
-- Name: initiative_role_permissions initiative_role_permissions_initiative_role_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_role_permissions
    ADD CONSTRAINT initiative_role_permissions_initiative_role_id_fkey FOREIGN KEY (initiative_role_id) REFERENCES guild_template.initiative_roles(id) ON DELETE CASCADE;


--
-- Name: initiative_roles initiative_roles_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_roles
    ADD CONSTRAINT initiative_roles_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;


--
-- Name: project_documents project_documents_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_documents
    ADD CONSTRAINT project_documents_document_id_fkey FOREIGN KEY (document_id) REFERENCES guild_template.documents(id) ON DELETE CASCADE;


--
-- Name: project_documents project_documents_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_documents
    ADD CONSTRAINT project_documents_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;


--
-- Name: project_favorites project_favorites_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_favorites
    ADD CONSTRAINT project_favorites_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;


--
-- Name: project_orders project_orders_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_orders
    ADD CONSTRAINT project_orders_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;


--
-- Name: project_tags project_tags_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_tags
    ADD CONSTRAINT project_tags_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;


--
-- Name: project_tags project_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.project_tags
    ADD CONSTRAINT project_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES guild_template.tags(id) ON DELETE CASCADE;


--
-- Name: projects projects_team_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.projects
    ADD CONSTRAINT projects_team_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);


--
-- Name: property_definitions property_definitions_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.property_definitions
    ADD CONSTRAINT property_definitions_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;


--
-- Name: queue_item_documents queue_item_documents_document_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_documents
    ADD CONSTRAINT queue_item_documents_document_id_fkey FOREIGN KEY (document_id) REFERENCES guild_template.documents(id);


--
-- Name: queue_item_documents queue_item_documents_queue_item_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_documents
    ADD CONSTRAINT queue_item_documents_queue_item_id_fkey FOREIGN KEY (queue_item_id) REFERENCES guild_template.queue_items(id);


--
-- Name: queue_item_tags queue_item_tags_queue_item_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_tags
    ADD CONSTRAINT queue_item_tags_queue_item_id_fkey FOREIGN KEY (queue_item_id) REFERENCES guild_template.queue_items(id);


--
-- Name: queue_item_tags queue_item_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_tags
    ADD CONSTRAINT queue_item_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES guild_template.tags(id);


--
-- Name: queue_item_tasks queue_item_tasks_queue_item_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_tasks
    ADD CONSTRAINT queue_item_tasks_queue_item_id_fkey FOREIGN KEY (queue_item_id) REFERENCES guild_template.queue_items(id);


--
-- Name: queue_item_tasks queue_item_tasks_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_item_tasks
    ADD CONSTRAINT queue_item_tasks_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id);


--
-- Name: queue_items queue_items_queue_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queue_items
    ADD CONSTRAINT queue_items_queue_id_fkey FOREIGN KEY (queue_id) REFERENCES guild_template.queues(id) ON DELETE CASCADE;


--
-- Name: queues queues_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.queues
    ADD CONSTRAINT queues_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);


--
-- Name: resource_grants resource_grants_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;


--
-- Name: resource_grants resource_grants_role_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_role_id_fkey FOREIGN KEY (role_id) REFERENCES guild_template.initiative_roles(id) ON DELETE CASCADE;


--
-- Name: task_assignees task_assignees_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_assignees
    ADD CONSTRAINT task_assignees_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id);


--
-- Name: task_assignment_digest_items task_assignment_digest_items_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items
    ADD CONSTRAINT task_assignment_digest_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;


--
-- Name: task_assignment_digest_items task_assignment_digest_items_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items
    ADD CONSTRAINT task_assignment_digest_items_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;


--
-- Name: task_property_values task_property_values_property_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_property_values
    ADD CONSTRAINT task_property_values_property_id_fkey FOREIGN KEY (property_id) REFERENCES guild_template.property_definitions(id) ON DELETE CASCADE;


--
-- Name: task_property_values task_property_values_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_property_values
    ADD CONSTRAINT task_property_values_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;


--
-- Name: task_statuses task_statuses_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_statuses
    ADD CONSTRAINT task_statuses_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;


--
-- Name: task_tags task_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_tags
    ADD CONSTRAINT task_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES guild_template.tags(id) ON DELETE CASCADE;


--
-- Name: task_tags task_tags_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.task_tags
    ADD CONSTRAINT task_tags_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;


--
-- Name: tasks tasks_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.tasks
    ADD CONSTRAINT tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id);


--
-- Name: initiative_members team_members_team_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.initiative_members
    ADD CONSTRAINT team_members_team_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);


--
-- Name: webhook_subscriptions webhook_subscriptions_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: initiative
--

ALTER TABLE ONLY guild_template.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;


--
-- Name: calendar_event_attendees; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.calendar_event_attendees ENABLE ROW LEVEL SECURITY;

--
-- Name: calendar_event_documents; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.calendar_event_documents ENABLE ROW LEVEL SECURITY;

--
-- Name: calendar_event_property_values; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.calendar_event_property_values ENABLE ROW LEVEL SECURITY;

--
-- Name: calendar_event_tags; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.calendar_event_tags ENABLE ROW LEVEL SECURITY;

--
-- Name: calendar_events; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.calendar_events ENABLE ROW LEVEL SECURITY;

--
-- Name: comments; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.comments ENABLE ROW LEVEL SECURITY;

--
-- Name: counter_groups; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.counter_groups ENABLE ROW LEVEL SECURITY;

--
-- Name: counters; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.counters ENABLE ROW LEVEL SECURITY;

--
-- Name: document_file_versions; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.document_file_versions ENABLE ROW LEVEL SECURITY;

--
-- Name: document_links; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.document_links ENABLE ROW LEVEL SECURITY;

--
-- Name: document_property_values; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.document_property_values ENABLE ROW LEVEL SECURITY;

--
-- Name: document_tags; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.document_tags ENABLE ROW LEVEL SECURITY;

--
-- Name: documents; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.documents ENABLE ROW LEVEL SECURITY;

--
-- Name: event_reminder_dispatches; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.event_reminder_dispatches ENABLE ROW LEVEL SECURITY;

--
-- Name: initiatives guild_level_open; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY guild_level_open ON guild_template.initiatives USING (true) WITH CHECK (true);


--
-- Name: tags guild_level_open; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY guild_level_open ON guild_template.tags USING (true) WITH CHECK (true);


--
-- Name: calendar_event_attendees initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.calendar_event_attendees FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_attendees.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_documents initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.calendar_event_documents FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_documents.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_property_values initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.calendar_event_property_values FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.calendar_events ce
     JOIN guild_template.property_definitions pd ON ((pd.id = calendar_event_property_values.property_id)))
  WHERE ((ce.id = calendar_event_property_values.event_id) AND (ce.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_tags initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.calendar_event_tags FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_tags.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_events initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.calendar_events FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: comments initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.comments FOR DELETE USING ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((document_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.documents d
  WHERE ((d.id = comments.document_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));


--
-- Name: counter_groups initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.counter_groups FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: counters initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.counters FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_file_versions initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.document_file_versions FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_file_versions.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_links initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.document_links FOR DELETE USING (((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.source_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.target_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))));


--
-- Name: document_property_values initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.document_property_values FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.documents d
     JOIN guild_template.property_definitions pd ON ((pd.id = document_property_values.property_id)))
  WHERE ((d.id = document_property_values.document_id) AND (d.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_tags initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.document_tags FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_tags.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: documents initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.documents FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: event_reminder_dispatches initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.event_reminder_dispatches FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = event_reminder_dispatches.event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_documents initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.project_documents FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_documents.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_favorites initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.project_favorites FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_orders initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.project_orders FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_tags initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.project_tags FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_tags.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: projects initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.projects FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: property_definitions initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.property_definitions FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: queue_item_documents initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.queue_item_documents FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_documents.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_item_tags initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.queue_item_tags FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tags.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_item_tasks initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.queue_item_tasks FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tasks.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_items initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.queue_items FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queues initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.queues FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: recent_views initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.recent_views FOR DELETE USING ((((entity_type = 'project'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = recent_views.entity_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'document'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = recent_views.entity_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'queue'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = recent_views.entity_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'counter_group'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = recent_views.entity_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));


--
-- Name: resource_grants initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.resource_grants FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: subtasks initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.subtasks FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = subtasks.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_assignees initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.task_assignees FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_assignment_digest_items initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.task_assignment_digest_items FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_property_values initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.task_property_values FOR DELETE USING ((EXISTS ( SELECT 1
   FROM ((guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
     JOIN guild_template.property_definitions pd ON ((pd.id = task_property_values.property_id)))
  WHERE ((tk.id = task_property_values.task_id) AND (pr.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_statuses initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.task_statuses FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_tags initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.task_tags FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_tags.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: tasks initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_delete ON guild_template.tasks FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_attendees initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.calendar_event_attendees FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_attendees.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_documents initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.calendar_event_documents FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_documents.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_property_values initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.calendar_event_property_values FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.calendar_events ce
     JOIN guild_template.property_definitions pd ON ((pd.id = calendar_event_property_values.property_id)))
  WHERE ((ce.id = calendar_event_property_values.event_id) AND (ce.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_tags initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.calendar_event_tags FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_tags.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_events initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.calendar_events FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: comments initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.comments FOR INSERT WITH CHECK ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((document_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.documents d
  WHERE ((d.id = comments.document_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));


--
-- Name: counter_groups initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.counter_groups FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: counters initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.counters FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_file_versions initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.document_file_versions FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_file_versions.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_links initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.document_links FOR INSERT WITH CHECK (((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.source_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.target_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))));


--
-- Name: document_property_values initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.document_property_values FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.documents d
     JOIN guild_template.property_definitions pd ON ((pd.id = document_property_values.property_id)))
  WHERE ((d.id = document_property_values.document_id) AND (d.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_tags initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.document_tags FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_tags.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: documents initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.documents FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: event_reminder_dispatches initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.event_reminder_dispatches FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = event_reminder_dispatches.event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_documents initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.project_documents FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_documents.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_favorites initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.project_favorites FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_orders initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.project_orders FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_tags initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.project_tags FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_tags.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: projects initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.projects FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: property_definitions initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.property_definitions FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: queue_item_documents initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.queue_item_documents FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_documents.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_item_tags initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.queue_item_tags FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tags.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_item_tasks initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.queue_item_tasks FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tasks.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_items initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.queue_items FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queues initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.queues FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: recent_views initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.recent_views FOR INSERT WITH CHECK ((((entity_type = 'project'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = recent_views.entity_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'document'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = recent_views.entity_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'queue'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = recent_views.entity_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'counter_group'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = recent_views.entity_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));


--
-- Name: resource_grants initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.resource_grants FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: subtasks initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.subtasks FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = subtasks.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_assignees initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.task_assignees FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_assignment_digest_items initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.task_assignment_digest_items FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_property_values initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.task_property_values FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM ((guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
     JOIN guild_template.property_definitions pd ON ((pd.id = task_property_values.property_id)))
  WHERE ((tk.id = task_property_values.task_id) AND (pr.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_statuses initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.task_statuses FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_tags initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.task_tags FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_tags.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: tasks initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_insert ON guild_template.tasks FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_attendees initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.calendar_event_attendees FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_attendees.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: calendar_event_documents initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.calendar_event_documents FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_documents.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: calendar_event_property_values initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.calendar_event_property_values FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.calendar_events ce
     JOIN guild_template.property_definitions pd ON ((pd.id = calendar_event_property_values.property_id)))
  WHERE ((ce.id = calendar_event_property_values.event_id) AND (ce.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: calendar_event_tags initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.calendar_event_tags FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_tags.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: calendar_events initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.calendar_events FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));


--
-- Name: comments initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.comments FOR SELECT USING ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((document_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.documents d
  WHERE ((d.id = comments.document_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))))));


--
-- Name: counter_groups initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.counter_groups FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));


--
-- Name: counters initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.counters FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: document_file_versions initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.document_file_versions FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_file_versions.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: document_links initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.document_links FOR SELECT USING (((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.source_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.target_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))));


--
-- Name: document_property_values initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.document_property_values FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.documents d
     JOIN guild_template.property_definitions pd ON ((pd.id = document_property_values.property_id)))
  WHERE ((d.id = document_property_values.document_id) AND (d.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: document_tags initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.document_tags FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_tags.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: documents initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.documents FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));


--
-- Name: event_reminder_dispatches initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.event_reminder_dispatches FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = event_reminder_dispatches.event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: project_documents initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.project_documents FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_documents.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: project_favorites initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.project_favorites FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: project_orders initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.project_orders FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: project_tags initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.project_tags FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_tags.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: projects initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.projects FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));


--
-- Name: property_definitions initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.property_definitions FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));


--
-- Name: queue_item_documents initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.queue_item_documents FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_documents.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: queue_item_tags initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.queue_item_tags FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tags.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: queue_item_tasks initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.queue_item_tasks FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tasks.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: queue_items initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.queue_items FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: queues initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.queues FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));


--
-- Name: recent_views initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.recent_views FOR SELECT USING ((((entity_type = 'project'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = recent_views.entity_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((entity_type = 'document'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = recent_views.entity_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((entity_type = 'queue'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = recent_views.entity_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((entity_type = 'counter_group'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = recent_views.entity_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))))));


--
-- Name: resource_grants initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.resource_grants FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));


--
-- Name: subtasks initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.subtasks FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = subtasks.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: task_assignees initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.task_assignees FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: task_assignment_digest_items initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.task_assignment_digest_items FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: task_property_values initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.task_property_values FOR SELECT USING ((EXISTS ( SELECT 1
   FROM ((guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
     JOIN guild_template.property_definitions pd ON ((pd.id = task_property_values.property_id)))
  WHERE ((tk.id = task_property_values.task_id) AND (pr.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: task_statuses initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.task_statuses FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: task_tags initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.task_tags FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_tags.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: tasks initiative_member_select; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_select ON guild_template.tasks FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));


--
-- Name: calendar_event_attendees initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.calendar_event_attendees FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_attendees.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_attendees.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_documents initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.calendar_event_documents FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_documents.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_documents.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_property_values initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.calendar_event_property_values FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.calendar_events ce
     JOIN guild_template.property_definitions pd ON ((pd.id = calendar_event_property_values.property_id)))
  WHERE ((ce.id = calendar_event_property_values.event_id) AND (ce.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.calendar_events ce
     JOIN guild_template.property_definitions pd ON ((pd.id = calendar_event_property_values.property_id)))
  WHERE ((ce.id = calendar_event_property_values.event_id) AND (ce.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_event_tags initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.calendar_event_tags FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_tags.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = calendar_event_tags.calendar_event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: calendar_events initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.calendar_events FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: comments initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.comments FOR UPDATE USING ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((document_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.documents d
  WHERE ((d.id = comments.document_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))))) WITH CHECK ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((document_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.documents d
  WHERE ((d.id = comments.document_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));


--
-- Name: counter_groups initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.counter_groups FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: counters initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.counters FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_file_versions initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.document_file_versions FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_file_versions.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_file_versions.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_links initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.document_links FOR UPDATE USING (((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.source_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.target_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))) WITH CHECK (((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.source_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_links.target_document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))));


--
-- Name: document_property_values initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.document_property_values FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.documents d
     JOIN guild_template.property_definitions pd ON ((pd.id = document_property_values.property_id)))
  WHERE ((d.id = document_property_values.document_id) AND (d.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.documents d
     JOIN guild_template.property_definitions pd ON ((pd.id = document_property_values.property_id)))
  WHERE ((d.id = document_property_values.document_id) AND (d.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: document_tags initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.document_tags FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_tags.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = document_tags.document_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: documents initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.documents FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: event_reminder_dispatches initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.event_reminder_dispatches FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = event_reminder_dispatches.event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.calendar_events
  WHERE ((calendar_events.id = event_reminder_dispatches.event_id) AND public.initiative_access(calendar_events.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_documents initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.project_documents FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_documents.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_documents.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_favorites initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.project_favorites FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_orders initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.project_orders FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: project_tags initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.project_tags FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_tags.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_tags.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: projects initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.projects FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: property_definitions initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.property_definitions FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: queue_item_documents initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.queue_item_documents FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_documents.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_documents.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_item_tags initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.queue_item_tags FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tags.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tags.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_item_tasks initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.queue_item_tasks FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tasks.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.queue_items qi
     JOIN guild_template.queues q ON ((q.id = qi.queue_id)))
  WHERE ((qi.id = queue_item_tasks.queue_item_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queue_items initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.queue_items FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: queues initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.queues FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: recent_views initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.recent_views FOR UPDATE USING ((((entity_type = 'project'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = recent_views.entity_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'document'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = recent_views.entity_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'queue'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = recent_views.entity_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'counter_group'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = recent_views.entity_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))))) WITH CHECK ((((entity_type = 'project'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = recent_views.entity_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'document'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.documents
  WHERE ((documents.id = recent_views.entity_id) AND public.initiative_access(documents.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'queue'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = recent_views.entity_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((entity_type = 'counter_group'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = recent_views.entity_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));


--
-- Name: resource_grants initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.resource_grants FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));


--
-- Name: subtasks initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.subtasks FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = subtasks.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = subtasks.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_assignees initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.task_assignees FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_assignment_digest_items initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.task_assignment_digest_items FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_property_values initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.task_property_values FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM ((guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
     JOIN guild_template.property_definitions pd ON ((pd.id = task_property_values.property_id)))
  WHERE ((tk.id = task_property_values.task_id) AND (pr.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM ((guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
     JOIN guild_template.property_definitions pd ON ((pd.id = task_property_values.property_id)))
  WHERE ((tk.id = task_property_values.task_id) AND (pr.initiative_id = pd.initiative_id) AND public.initiative_access(pd.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_statuses initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.task_statuses FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: task_tags initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.task_tags FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_tags.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_tags.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: tasks initiative_member_update; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY initiative_member_update ON guild_template.tasks FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));


--
-- Name: initiatives; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.initiatives ENABLE ROW LEVEL SECURITY;

--
-- Name: project_documents; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.project_documents ENABLE ROW LEVEL SECURITY;

--
-- Name: project_favorites; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.project_favorites ENABLE ROW LEVEL SECURITY;

--
-- Name: project_orders; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.project_orders ENABLE ROW LEVEL SECURITY;

--
-- Name: project_tags; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.project_tags ENABLE ROW LEVEL SECURITY;

--
-- Name: projects; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.projects ENABLE ROW LEVEL SECURITY;

--
-- Name: property_definitions; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.property_definitions ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_item_documents; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.queue_item_documents ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_item_tags; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.queue_item_tags ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_item_tasks; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.queue_item_tasks ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_items; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.queue_items ENABLE ROW LEVEL SECURITY;

--
-- Name: queues; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.queues ENABLE ROW LEVEL SECURITY;

--
-- Name: recent_views; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.recent_views ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_grants; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.resource_grants ENABLE ROW LEVEL SECURITY;

--
-- Name: calendar_events soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.calendar_events AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: comments soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.comments AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: counter_groups soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.counter_groups AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: counters soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.counters AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: documents soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.documents AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: initiatives soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.initiatives AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: projects soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.projects AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: queue_items soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.queue_items AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: queues soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.queues AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: tags soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.tags AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: tasks soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: initiative
--

CREATE POLICY soft_delete_admin_purge ON guild_template.tasks AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));


--
-- Name: subtasks; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.subtasks ENABLE ROW LEVEL SECURITY;

--
-- Name: tags; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.tags ENABLE ROW LEVEL SECURITY;

--
-- Name: task_assignees; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.task_assignees ENABLE ROW LEVEL SECURITY;

--
-- Name: task_assignment_digest_items; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.task_assignment_digest_items ENABLE ROW LEVEL SECURITY;

--
-- Name: task_property_values; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.task_property_values ENABLE ROW LEVEL SECURITY;

--
-- Name: task_statuses; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.task_statuses ENABLE ROW LEVEL SECURITY;

--
-- Name: task_tags; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.task_tags ENABLE ROW LEVEL SECURITY;

--
-- Name: tasks; Type: ROW SECURITY; Schema: guild_template; Owner: initiative
--

ALTER TABLE guild_template.tasks ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

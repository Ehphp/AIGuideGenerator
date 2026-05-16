export type SessionStatus =
    | "created"
    | "uploaded"
    | "processing"
    | "ready"
    | "failed";

export type SourceType = "recorded" | "uploaded";

export interface GuideAction {
    verb: string;
    target: string;
    value?: string | null;
}

export interface GuideEvidence {
    frame_keys: string[];
    transcript_excerpt: string;
    t_start?: number | null;
    t_end?: number | null;
}

export interface GuideStep {
    id: string;
    order: number;
    title: string;
    description: string;
    actions: GuideAction[];
    evidence: GuideEvidence;
    warnings: string[];
    notes: string[];
    confidence: number;
}

export interface GuideTroubleshooting {
    symptom: string;
    likely_cause: string;
    resolution: string;
}

export interface GuideMetadata {
    generated_by?: string;
    generated_at?: string;
    source_session_id?: string;
    source_duration_sec?: number | null;
}

export interface Guide {
    schema_version: string;
    title: string;
    summary: string;
    estimated_duration_minutes?: number | null;
    prerequisites: string[];
    tools_or_systems: string[];
    steps: GuideStep[];
    warnings: string[];
    notes: string[];
    troubleshooting?: GuideTroubleshooting[];
    metadata?: GuideMetadata;
}

export interface PipelineEvent {
    t: string;
    stage: string;
    level: string;
    message: string;
}

export interface AiUsageCall {
    stage?: string;
    model?: string;
    input_chars?: number;
    output_chars?: number;
    ts?: string;
}

export interface AiUsage {
    models?: {
        stt?: string;
        vision?: string;
        llm?: string;
        ocr?: string;
    };
    audio_duration_sec?: number;
    frame_count?: number;
    approx_input_chars?: number;
    calls?: AiUsageCall[];
}

export interface Session {
    id: string;
    title: string | null;
    status: SessionStatus;
    progress_message: string | null;
    source_type: SourceType | null;
    media_key: string | null;
    media_mime: string | null;
    media_duration_sec: number | null;
    media_size_bytes: number | null;
    pipeline_events: PipelineEvent[];
    pipeline_artifacts?: Record<string, unknown>;
    ai_usage?: AiUsage | null;
    error: string | null;
    guide_content: Guide | null;
    guide_schema_version: string | null;
    guide_edited_at?: string | null;
    created_at: string;
    updated_at: string;
}

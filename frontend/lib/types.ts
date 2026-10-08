// FastAPI（backend/app/schemas.py）と対応する型定義

export type MeetingStatus =
  | "UPLOADED"
  | "TRANSCRIBING"
  | "TRANSCRIBED"
  | "ANALYZING"
  | "GENERATING"
  | "GENERATED"
  | "UPLOADING"
  | "COMPLETED"
  | "ERROR";

export type PipelineStep = "transcribe" | "analyze" | "generate" | "dropbox";
export type MeetingTool = "zoom" | "google_meet" | "teams" | "other";
export type InputType = "audio" | "video" | "text";
export type FileType = "transcript" | "docx" | "pdf";

export interface Participant {
  id: string;
  name: string;
  email: string | null;
}

export interface Meeting {
  id: string;
  meeting_name: string;
  meeting_datetime: string;
  meeting_tool: MeetingTool;
  input_type: InputType;
  source_file_name: string | null;
  status: MeetingStatus;
  error_step: PipelineStep | null;
  error_message: string | null;
  dropbox_folder_path: string | null;
  created_at: string;
  updated_at: string;
  participants: Participant[];
}

export interface MeetingCreate {
  meeting_name: string;
  meeting_datetime: string;
  meeting_tool: MeetingTool;
  participants: string[];
  input_type: InputType;
  file_name: string;
  file_size: number;
}

export interface MeetingCreateResponse {
  meeting: Meeting;
  upload_path: string;
  upload_token: string;
}

export interface DiscussionItem {
  topic: string;
  content: string;
}

export interface TodoItem {
  task: string;
  assignee: string;
  deadline: string;
}

export interface Minutes {
  meeting_id: string;
  ai_model: string | null;
  summary: string;
  discussion: DiscussionItem[];
  decisions: string[];
  todos: TodoItem[];
  unresolved_items: string[];
  next_actions: string[];
}

export interface FileUrl {
  url: string;
  file_name: string;
}

export interface DropboxStatus {
  connected: boolean;
  email: string | null;
  configured: boolean;
}

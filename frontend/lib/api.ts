import { getSupabase } from "./supabase";
import type { DropboxStatus, FileType, FileUrl, Meeting, MeetingCreate, MeetingCreateResponse, Minutes } from "./types";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await getSupabase().auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError("ログインが必要です。", 401);

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        Authorization: `Bearer ${token}`,
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError("サーバーに接続できませんでした。しばらくしてから再度お試しください。", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : "処理に失敗しました。入力内容を確認してください。";
    throw new ApiError(message, res.status);
  }
  return body as T;
}

export const api = {
  listMeetings: () => request<Meeting[]>("/api/meetings"),
  getMeeting: (id: string) => request<Meeting>(`/api/meetings/${id}`),
  createMeeting: (body: MeetingCreate) =>
    request<MeetingCreateResponse>("/api/meetings", { method: "POST", body: JSON.stringify(body) }),
  processMeeting: (id: string) => request<Meeting>(`/api/meetings/${id}/process`, { method: "POST" }),
  getMinutes: (id: string) => request<Minutes>(`/api/meetings/${id}/minutes`),
  getFileUrl: (id: string, type: FileType) => request<FileUrl>(`/api/meetings/${id}/files/${type}`),
  saveToDropbox: (id: string) => request<Meeting>(`/api/meetings/${id}/dropbox`, { method: "POST" }),
  dropboxStatus: () => request<DropboxStatus>("/api/dropbox/status"),
  dropboxConnect: () => request<{ authorize_url: string }>("/api/dropbox/connect"),
  dropboxDisconnect: () => request<void>("/api/dropbox/connection", { method: "DELETE" }),
};

/** FastAPI が発行した署名付きトークンで、ファイルを Supabase Storage に直接アップロードする */
export async function uploadToStorage(path: string, token: string, file: Blob): Promise<void> {
  const { error } = await getSupabase().storage.from("uploads").uploadToSignedUrl(path, token, file);
  if (error) throw new ApiError("ファイルのアップロードに失敗しました。通信環境を確認して再度お試しください。", 0);
}

import * as http from "http";
import * as https from "https";
import { URL } from "url";
import { EventEmitter } from "events";

export interface SSEEvent {
  type: string;
  agent: string;
  message: string;
  data?: Record<string, unknown>;
}

export class BackendClient extends EventEmitter {
  private baseUrl: string;

  constructor(baseUrl: string) {
    super();
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async get<T>(path: string): Promise<T> {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      const mod = url.protocol === "https:" ? https : http;
      mod
        .get(url.toString(), (res) => {
          let data = "";
          res.on("data", (chunk: Buffer) => (data += chunk.toString()));
          res.on("end", () => {
            try {
              resolve(JSON.parse(data));
            } catch {
              reject(new Error(`Invalid JSON response: ${data.slice(0, 200)}`));
            }
          });
        })
        .on("error", reject);
    });
  }

  async post<T>(path: string, body: unknown): Promise<T> {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      const payload = JSON.stringify(body);
      const options = {
        hostname: url.hostname,
        port: url.port || (url.protocol === "https:" ? 443 : 80),
        path: url.pathname + url.search,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
        },
      };
      const mod = url.protocol === "https:" ? https : http;
      const req = mod.request(options, (res) => {
        let data = "";
        res.on("data", (chunk: Buffer) => (data += chunk.toString()));
        res.on("end", () => {
          try {
            resolve(JSON.parse(data));
          } catch {
            reject(new Error(`Invalid JSON: ${data.slice(0, 200)}`));
          }
        });
      });
      req.on("error", reject);
      req.write(payload);
      req.end();
    });
  }

  async delete<T>(path: string, body?: unknown): Promise<T> {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      const payload = body ? JSON.stringify(body) : "";
      const options = {
        hostname: url.hostname,
        port: url.port || (url.protocol === "https:" ? 443 : 80),
        path: url.pathname + url.search,
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
        },
      };
      const mod = url.protocol === "https:" ? https : http;
      const req = mod.request(options, (res) => {
        let data = "";
        res.on("data", (chunk: Buffer) => (data += chunk.toString()));
        res.on("end", () => {
          try { resolve(JSON.parse(data || "{}")); }
          catch { resolve({} as T); }
        });
      });
      req.on("error", reject);
      if (payload) req.write(payload);
      req.end();
    });
  }

  /** Stream SSE events from the backend. Returns a cleanup function. */
  streamSSE(
    path: string,
    body: unknown,
    onEvent: (event: SSEEvent) => void,
    onEnd: () => void,
    onError: (err: Error) => void
  ): () => void {
    const url = new URL(this.baseUrl + path);
    const payload = JSON.stringify(body);
    const options = {
      hostname: url.hostname,
      port: url.port || 80,
      path: url.pathname + url.search,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
        Accept: "text/event-stream",
      },
    };

    const mod = url.protocol === "https:" ? https : http;
    const req = mod.request(options, (res) => {
      let buffer = "";
      res.setEncoding("utf8");
      res.on("data", (chunk: string) => {
        buffer += chunk;
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const raw = line.slice(6).trim();
            if (!raw) continue;
            try {
              const event: SSEEvent = JSON.parse(raw);
              onEvent(event);
            } catch {
              /* malformed event */
            }
          }
        }
      });
      res.on("end", onEnd);
      res.on("error", onError);
    });

    req.on("error", onError);
    req.write(payload);
    req.end();

    return () => req.destroy();
  }

  async checkHealth(): Promise<{ status: string; ollama_online: boolean; models: string[] }> {
    try {
      return await this.get("/health");
    } catch {
      return { status: "unreachable", ollama_online: false, models: [] };
    }
  }
}

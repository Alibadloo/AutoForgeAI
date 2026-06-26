import * as vscode from "vscode";
import { BackendClient, SSEEvent } from "../services/BackendClient";

export class AgentPanel {
  public static currentPanel: AgentPanel | undefined;
  private static readonly viewType = "autoforgePanel";

  private readonly _panel: vscode.WebviewPanel;
  private readonly _client: BackendClient;
  private _cancelStream?: () => void;
  private _disposables: vscode.Disposable[] = [];

  private constructor(panel: vscode.WebviewPanel, client: BackendClient) {
    this._panel = panel;
    this._client = client;

    this._panel.webview.html = this._getHtml();
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    this._panel.webview.onDidReceiveMessage(
      (msg) => this._handleMessage(msg),
      null,
      this._disposables
    );
  }

  static createOrShow(extensionUri: vscode.Uri, client: BackendClient): void {
    const column = vscode.window.activeTextEditor
      ? vscode.ViewColumn.Beside
      : vscode.ViewColumn.One;

    if (AgentPanel.currentPanel) {
      AgentPanel.currentPanel._panel.reveal(column);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      AgentPanel.viewType,
      "AutoForge AI",
      column,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(extensionUri, "media")],
      }
    );

    AgentPanel.currentPanel = new AgentPanel(panel, client);
  }

  private async _handleMessage(message: { command: string; payload?: unknown }): Promise<void> {
    switch (message.command) {
      case "forge":
        await this._forge(message.payload as Record<string, unknown>);
        break;
      case "debug":
        await this._debug(message.payload as Record<string, unknown>);
        break;
      case "evolve":
        await this._evolve(message.payload as Record<string, unknown>);
        break;
      case "checkStatus":
        await this._checkStatus();
        break;
      case "cancel":
        this._cancelStream?.();
        this._post("streamEnd", {});
        break;
      case "loadModels":
        await this._loadModels();
        break;
      case "pullModel":
        await this._pullModel((message.payload as Record<string, unknown>).name as string);
        break;
      case "deleteModel":
        await this._deleteModel((message.payload as Record<string, unknown>).name as string);
        break;
      case "updateModelConfig":
        await this._updateModelConfig(message.payload as Record<string, string>);
        break;
    }
  }

  private async _forge(payload: Record<string, unknown>): Promise<void> {
    this._cancelStream?.();
    this._post("streamStart", { title: "Forging project…" });
    const projectPath =
      (payload.projectPath as string) ||
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      "";

    const cancel = this._client.streamSSE(
      "/forge",
      { ...payload, project_path: projectPath },
      (e) => this._post("event", e),
      () => this._post("streamEnd", {}),
      (err) => this._post("error", { message: err.message })
    );
    this._cancelStream = cancel;
  }

  private async _debug(payload: Record<string, unknown>): Promise<void> {
    this._cancelStream?.();
    this._post("streamStart", { title: "Debugging build…" });
    const projectPath =
      (payload.projectPath as string) ||
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      "";

    const cancel = this._client.streamSSE(
      "/debug",
      { project_path: projectPath, command: payload.command || "dotnet build" },
      (e) => this._post("event", e),
      () => this._post("streamEnd", {}),
      (err) => this._post("error", { message: err.message })
    );
    this._cancelStream = cancel;
  }

  private async _evolve(payload: Record<string, unknown>): Promise<void> {
    this._cancelStream?.();
    this._post("streamStart", { title: "Running evolution analysis…" });
    const projectPath =
      (payload.projectPath as string) ||
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      "";

    const cancel = this._client.streamSSE(
      "/evolve",
      { project_path: projectPath },
      (e) => this._post("event", e),
      () => this._post("streamEnd", {}),
      (err) => this._post("error", { message: err.message })
    );
    this._cancelStream = cancel;
  }

  private async _checkStatus(): Promise<void> {
    const health = await this._client.checkHealth();
    this._post("status", health);
  }

  private async _loadModels(): Promise<void> {
    try {
      const data = await this._client.get<{ installed: unknown[]; recommended: unknown[] }>("/models");
      const cfg = await this._client.get<{ models: Record<string, string> }>("/models/config");
      this._post("modelsData", { ...data, config: cfg.models });
    } catch (e) {
      this._post("error", { message: String(e) });
    }
  }

  private async _pullModel(name: string): Promise<void> {
    this._client.streamSSE(
      "/models/pull",
      { name },
      (event) => {
        const raw = event as unknown as Record<string, unknown>;
        this._post("pullProgress", {
          name,
          status: raw["status"] ?? "pulling",
          completed: raw["completed"] ?? 0,
          total: raw["total"] ?? 0,
        });
      },
      () => this._post("pullProgress", { name, status: "done", completed: 1, total: 1 }),
      (err) => this._post("error", { message: err.message })
    );
  }

  private async _deleteModel(name: string): Promise<void> {
    try {
      await this._client.delete(`/models/${encodeURIComponent(name)}`);
      await this._loadModels();
    } catch (e) {
      this._post("error", { message: String(e) });
    }
  }

  private async _updateModelConfig(config: Record<string, string>): Promise<void> {
    try {
      const result = await this._client.post<{ current: Record<string, string> }>("/models/config", config);
      this._post("modelConfigUpdated", result.current);
    } catch (e) {
      this._post("error", { message: String(e) });
    }
  }

  private _post(command: string, data: unknown): void {
    this._panel.webview.postMessage({ command, data });
  }

  dispose(): void {
    AgentPanel.currentPanel = undefined;
    this._cancelStream?.();
    this._panel.dispose();
    for (const d of this._disposables) d.dispose();
  }

  private _getHtml(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>AutoForge AI</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #e6edf3; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; }
  header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); padding: 12px 16px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid #30363d; }
  header h1 { font-size: 16px; font-weight: 700; background: linear-gradient(90deg, #58a6ff, #bc8cff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .badge { background: #238636; color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 10px; font-weight: 600; }
  .tab-bar { display: flex; background: #161b22; border-bottom: 1px solid #30363d; }
  .tab { padding: 8px 16px; cursor: pointer; font-size: 13px; color: #8b949e; border-bottom: 2px solid transparent; transition: all 0.2s; }
  .tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }
  .tab:hover { color: #e6edf3; }
  .content { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
  .panel { display: none; flex: 1; flex-direction: column; padding: 16px; gap: 12px; overflow-y: auto; }
  .panel.active { display: flex; }
  label { font-size: 12px; color: #8b949e; margin-bottom: 4px; display: block; }
  input, textarea, select { background: #161b22; border: 1px solid #30363d; color: #e6edf3; border-radius: 6px; padding: 8px 12px; width: 100%; font-size: 13px; outline: none; transition: border-color 0.2s; }
  input:focus, textarea:focus, select:focus { border-color: #58a6ff; }
  textarea { resize: vertical; min-height: 80px; }
  .btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.2s; }
  .btn-primary { background: linear-gradient(135deg, #238636, #2ea043); color: #fff; }
  .btn-primary:hover { background: linear-gradient(135deg, #2ea043, #3fb950); }
  .btn-danger { background: #b62324; color: #fff; }
  .btn-secondary { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
  .btn-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .log-container { flex: 1; background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 12px; overflow-y: auto; font-family: 'Cascadia Code', 'Courier New', monospace; font-size: 12px; min-height: 200px; max-height: 400px; }
  .log-entry { padding: 3px 0; border-bottom: 1px solid #161b22; line-height: 1.5; }
  .log-entry .agent { color: #bc8cff; font-weight: 600; }
  .log-entry.start .msg { color: #58a6ff; }
  .log-entry.done .msg { color: #3fb950; }
  .log-entry.error .msg { color: #f85149; }
  .log-entry.file .msg { color: #79c0ff; }
  .log-entry.build-ok .msg { color: #3fb950; font-weight: 700; }
  .log-entry.build-err .msg { color: #f85149; font-weight: 700; }
  .log-entry.complete .msg { color: #ffa657; font-weight: 700; font-size: 13px; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .status-ok { background: #3fb950; }
  .status-err { background: #f85149; }
  .status-bar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: #161b22; border-top: 1px solid #30363d; font-size: 11px; color: #8b949e; }
  .progress { height: 3px; background: #30363d; border-radius: 2px; overflow: hidden; }
  .progress-bar { height: 100%; background: linear-gradient(90deg, #58a6ff, #bc8cff); width: 0%; transition: width 0.3s; animation: none; }
  .progress-bar.running { animation: pulse 1.5s ease-in-out infinite; width: 100%; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
  .findings { display: flex; flex-direction: column; gap: 8px; }
  .finding { background: #161b22; border-radius: 6px; padding: 10px; border-left: 3px solid #f85149; }
  .finding.MEDIUM { border-left-color: #ffa657; }
  .finding.LOW { border-left-color: #58a6ff; }
  .finding-type { font-size: 11px; color: #8b949e; font-weight: 600; text-transform: uppercase; }
  .finding-issue { color: #e6edf3; font-size: 13px; margin: 4px 0; }
  .finding-fix { color: #3fb950; font-size: 12px; }
  .model-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; display: flex; align-items: center; gap: 10px; }
  .model-card.installed { border-color: #238636; }
  .model-info { flex: 1; }
  .model-name { font-size: 13px; font-weight: 600; color: #e6edf3; font-family: monospace; }
  .model-meta { font-size: 11px; color: #8b949e; margin-top: 2px; }
  .model-roles { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
  .role-tag { background: #1f2937; border: 1px solid #374151; color: #79c0ff; font-size: 10px; padding: 1px 6px; border-radius: 10px; }
  .model-actions { display: flex; gap: 6px; align-items: center; }
  .btn-sm { padding: 4px 10px; font-size: 11px; }
  .install-badge { background: #238636; color: #fff; font-size: 10px; padding: 2px 8px; border-radius: 10px; }
  .pull-progress { font-size: 11px; color: #ffa657; margin-top: 4px; }
  .role-config { display: grid; grid-template-columns: 80px 1fr; gap: 8px; align-items: center; }
  .role-label { font-size: 12px; color: #8b949e; font-weight: 600; text-transform: uppercase; }
  .section-title { font-size: 13px; font-weight: 700; color: #ffa657; border-bottom: 1px solid #30363d; padding-bottom: 6px; }
</style>
</head>
<body>
<header>
  <span style="font-size:20px">⚡</span>
  <h1>AutoForge AI</h1>
  <span class="badge" id="statusBadge">checking…</span>
</header>
<div class="progress"><div class="progress-bar" id="progressBar"></div></div>

<div class="tab-bar">
  <div class="tab active" onclick="switchTab('forge')">🔨 Forge</div>
  <div class="tab" onclick="switchTab('debug')">🐛 Debug</div>
  <div class="tab" onclick="switchTab('evolve')">🧬 Evolution</div>
  <div class="tab" onclick="switchTab('models')">🤖 Models</div>
  <div class="tab" onclick="switchTab('log')">📋 Log</div>
  <div class="tab" onclick="switchTab('about')">ℹ About</div>
</div>

<!-- FORGE TAB -->
<div class="panel active" id="panel-forge">
  <div>
    <label>Project description</label>
    <textarea id="forgePrompt" placeholder="Describe the project you want to build…&#10;e.g. A warehouse management API with C# .NET 8, PostgreSQL, Clean Architecture, REST API with JWT auth"></textarea>
  </div>
  <div>
    <label>Output folder (leave empty = current workspace)</label>
    <input id="forgePath" placeholder="/path/to/output/folder"/>
  </div>
  <div>
    <label>Tech stack hints (optional)</label>
    <input id="forgeTech" placeholder="e.g. C# .NET 8, React, PostgreSQL"/>
  </div>
  <div>
    <label>Coding rules (comma-separated)</label>
    <input id="forgeRules" value="clean-architecture, async-all, solid"/>
  </div>
  <div class="btn-row">
    <button class="btn btn-primary" onclick="runForge()">⚡ Forge Project</button>
    <button class="btn btn-danger" onclick="cancel()">⏹ Cancel</button>
  </div>
  <div id="forgeLog" class="log-container"></div>
</div>

<!-- DEBUG TAB -->
<div class="panel" id="panel-debug">
  <div>
    <label>Project folder</label>
    <input id="debugPath" placeholder="Leave empty to use current workspace"/>
  </div>
  <div>
    <label>Build command</label>
    <input id="debugCommand" value="dotnet build"/>
  </div>
  <div>
    <label>Paste build errors (optional — skip to run fresh build)</label>
    <textarea id="debugErrors" placeholder="Paste build errors here…" style="min-height:60px"></textarea>
  </div>
  <div class="btn-row">
    <button class="btn btn-primary" onclick="runDebug()">🐛 Debug & Fix</button>
    <button class="btn btn-danger" onclick="cancel()">⏹ Cancel</button>
  </div>
  <div id="debugLog" class="log-container"></div>
</div>

<!-- EVOLVE TAB -->
<div class="panel" id="panel-evolve">
  <p style="color:#8b949e;font-size:13px">Run AI code quality analysis on an existing project. Automatically detects duplicate code, missing async, SOLID violations, and slow queries.</p>
  <div>
    <label>Project folder</label>
    <input id="evolvePath" placeholder="Leave empty to use current workspace"/>
  </div>
  <div class="btn-row">
    <button class="btn btn-primary" onclick="runEvolve()">🧬 Run Evolution</button>
    <button class="btn btn-danger" onclick="cancel()">⏹ Cancel</button>
  </div>
  <div id="evolveLog" class="log-container"></div>
  <div class="findings" id="findings"></div>
</div>

<!-- LOG TAB -->
<div class="panel" id="panel-log">
  <div class="btn-row">
    <button class="btn btn-secondary" onclick="clearLog()">🗑 Clear Log</button>
    <button class="btn btn-secondary" onclick="checkStatus()">🔍 Check Status</button>
  </div>
  <div id="masterLog" class="log-container" style="max-height:500px"></div>
</div>

<!-- MODELS TAB -->
<div class="panel" id="panel-models">
  <div class="section-title">Role Configuration</div>
  <p style="color:#8b949e;font-size:12px">Assign which Ollama model is used for each agent role:</p>
  <div class="role-config" id="roleConfig">
    <span class="role-label">Planner</span>
    <select id="roleSelect-planner" onchange="updateRole('planner',this.value)"><option>loading…</option></select>
    <span class="role-label">Coder</span>
    <select id="roleSelect-coder" onchange="updateRole('coder',this.value)"><option>loading…</option></select>
    <span class="role-label">Reviewer</span>
    <select id="roleSelect-reviewer" onchange="updateRole('reviewer',this.value)"><option>loading…</option></select>
    <span class="role-label">Fast</span>
    <select id="roleSelect-fast" onchange="updateRole('fast',this.value)"><option>loading…</option></select>
  </div>
  <div class="btn-row" style="margin-top:4px">
    <button class="btn btn-secondary btn-sm" onclick="loadModels()">🔄 Refresh</button>
  </div>

  <div class="section-title" style="margin-top:8px">Installed Models</div>
  <div id="installedModels" style="display:flex;flex-direction:column;gap:6px"></div>

  <div class="section-title" style="margin-top:8px">Recommended Models</div>
  <p style="color:#8b949e;font-size:12px">Click Install to download via Ollama:</p>
  <div id="recommendedModels" style="display:flex;flex-direction:column;gap:6px"></div>
</div>

<!-- ABOUT TAB -->
<div class="panel" id="panel-about">
  <div style="text-align:center;padding:20px 0">
    <div style="font-size:48px">⚡</div>
    <h2 style="background:linear-gradient(90deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:24px;margin:8px 0">AutoForge AI</h2>
    <p style="color:#8b949e;font-size:13px">Autonomous local AI software engineer</p>
    <p style="color:#8b949e;font-size:12px;margin-top:4px">v1.0.0 · Powered by Ollama · 100% Local</p>
  </div>

  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px">
    <div style="font-size:13px;font-weight:700;color:#ffa657;margin-bottom:10px">👤 Developer</div>
    <div style="display:flex;flex-direction:column;gap:8px">
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:20px">🧑‍💻</span>
        <div>
          <div style="font-size:14px;font-weight:700;color:#e6edf3">Ali Badloo</div>
          <div style="font-size:11px;color:#8b949e">Software Engineer · Industrial Automation · AI/LLM</div>
        </div>
      </div>
      <a href="https://github.com/alibadlu2020" style="display:flex;align-items:center;gap:8px;color:#58a6ff;text-decoration:none;font-size:13px;padding:6px 10px;background:#0d1117;border-radius:6px;border:1px solid #30363d">
        <span style="font-size:16px">🐙</span> github.com/alibadlu2020
      </a>
      <a href="https://instagram.com/alibadlu2020" style="display:flex;align-items:center;gap:8px;color:#e1306c;text-decoration:none;font-size:13px;padding:6px 10px;background:#0d1117;border-radius:6px;border:1px solid #30363d">
        <span style="font-size:16px">📸</span> instagram.com/alibadlu2020
      </a>
    </div>
  </div>

  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px">
    <div style="font-size:13px;font-weight:700;color:#ffa657;margin-bottom:10px">💻 Recommended Coder Models</div>
    <p style="color:#8b949e;font-size:12px;margin-bottom:10px">For best code generation, install one of these models:</p>
    <div style="display:flex;flex-direction:column;gap:6px">
      <div style="background:#0d1117;border-radius:6px;padding:10px;border-left:3px solid #3fb950">
        <div style="font-size:13px;font-weight:600;color:#e6edf3;font-family:monospace">qwen2.5-coder:7b</div>
        <div style="font-size:11px;color:#8b949e;margin-top:2px">4-8 GB VRAM · ★★★ Excellent — Best choice for most GPUs</div>
        <div style="margin-top:6px"><button class="btn btn-primary btn-sm" onclick="installRecommended('qwen2.5-coder:7b')">⬇ Install</button></div>
      </div>
      <div style="background:#0d1117;border-radius:6px;padding:10px;border-left:3px solid #58a6ff">
        <div style="font-size:13px;font-weight:600;color:#e6edf3;font-family:monospace">qwen2.5-coder:14b</div>
        <div style="font-size:11px;color:#8b949e;margin-top:2px">8-12 GB VRAM · ★★★★ Best quality for mid-range GPUs</div>
        <div style="margin-top:6px"><button class="btn btn-primary btn-sm" onclick="installRecommended('qwen2.5-coder:14b')">⬇ Install</button></div>
      </div>
      <div style="background:#0d1117;border-radius:6px;padding:10px;border-left:3px solid #bc8cff">
        <div style="font-size:13px;font-weight:600;color:#e6edf3;font-family:monospace">qwen2.5-coder:32b</div>
        <div style="font-size:11px;color:#8b949e;margin-top:2px">20+ GB VRAM · ★★★★★ Top quality</div>
        <div style="margin-top:6px"><button class="btn btn-primary btn-sm" onclick="installRecommended('qwen2.5-coder:32b')">⬇ Install</button></div>
      </div>
    </div>
  </div>

  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px">
    <div style="font-size:13px;font-weight:700;color:#ffa657;margin-bottom:8px">🤖 8 Specialized Agents</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px">
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Architect</b><br><span style="color:#8b949e">designs architecture</span></div>
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Backend</b><br><span style="color:#8b949e">generates API code</span></div>
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Frontend</b><br><span style="color:#8b949e">builds UI components</span></div>
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Database</b><br><span style="color:#8b949e">SQL + migrations</span></div>
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Debug</b><br><span style="color:#8b949e">build → fix loop</span></div>
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Documentation</b><br><span style="color:#8b949e">README + API docs</span></div>
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Git</b><br><span style="color:#8b949e">init + commit</span></div>
      <div style="padding:6px;background:#0d1117;border-radius:4px"><b style="color:#58a6ff">Evolution</b><br><span style="color:#8b949e">nightly code review</span></div>
    </div>
  </div>

  <div style="text-align:center;color:#30363d;font-size:11px;padding:8px">MIT License · github.com/alibadlu2020/AutoForgeAI</div>
</div>

<div class="status-bar">
  <span class="status-dot" id="statusDot" style="background:#8b949e"></span>
  <span id="statusText">Connecting…</span>
</div>

<script>
const vscode = acquireVsCodeApi();
let activeLog = document.getElementById('forgeLog');

const TABS = ['forge','debug','evolve','models','log','about'];

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const idx = TABS.indexOf(tab);
  if (idx >= 0) document.querySelectorAll('.tab')[idx].classList.add('active');
  document.getElementById('panel-' + tab).classList.add('active');
  activeLog = document.getElementById(tab + 'Log') || document.getElementById('masterLog');
  if (tab === 'models') loadModels();
}

function runForge() {
  activeLog = document.getElementById('forgeLog');
  clearEl(activeLog);
  const rules = document.getElementById('forgeRules').value.split(',').map(r => r.trim()).filter(Boolean);
  const tech = document.getElementById('forgeTech').value;
  vscode.postMessage({ command: 'forge', payload: {
    prompt: document.getElementById('forgePrompt').value,
    projectPath: document.getElementById('forgePath').value,
    rules,
    tech_stack: tech ? { custom: tech } : {}
  }});
}

function runDebug() {
  activeLog = document.getElementById('debugLog');
  clearEl(activeLog);
  vscode.postMessage({ command: 'debug', payload: {
    projectPath: document.getElementById('debugPath').value,
    command: document.getElementById('debugCommand').value,
    errorOutput: document.getElementById('debugErrors').value
  }});
}

function runEvolve() {
  activeLog = document.getElementById('evolveLog');
  clearEl(activeLog);
  document.getElementById('findings').innerHTML = '';
  vscode.postMessage({ command: 'evolve', payload: {
    projectPath: document.getElementById('evolvePath').value
  }});
}

function cancel() { vscode.postMessage({ command: 'cancel' }); }
function checkStatus() { vscode.postMessage({ command: 'checkStatus' }); }

// ── Model management ─────────────────────────────────────────────────────────
let _installedModels = [];
let _currentConfig = {};

function loadModels() { vscode.postMessage({ command: 'loadModels' }); }

function updateRole(role, model) {
  vscode.postMessage({ command: 'updateModelConfig', payload: { [role]: model } });
}

function pullModel(name, btnEl) {
  btnEl.textContent = 'Pulling…';
  btnEl.disabled = true;
  vscode.postMessage({ command: 'pullModel', payload: { name } });
}

function deleteModel(name) {
  if (!confirm('Delete model ' + name + '?')) return;
  vscode.postMessage({ command: 'deleteModel', payload: { name } });
}

function installRecommended(name) {
  switchTab('models');
  setTimeout(() => {
    const btnId = 'btn-' + name.replace(/[:.]/g, '_');
    const btn = document.getElementById(btnId);
    if (btn) { pullModel(name, btn); } else {
      vscode.postMessage({ command: 'pullModel', payload: { name } });
    }
  }, 300);
}

function renderModelTab(data) {
  _installedModels = (data.installed || []).map(m => m.name || m);
  _currentConfig = data.config || {};
  const recommended = data.recommended || [];

  // Update role dropdowns
  const roles = ['planner','coder','reviewer','fast'];
  roles.forEach(role => {
    const sel = document.getElementById('roleSelect-' + role);
    if (!sel) return;
    sel.innerHTML = _installedModels.map(m =>
      \`<option value="\${m}" \${_currentConfig[role]===m?'selected':''}>\${m}</option>\`
    ).join('') || '<option>No models installed</option>';
  });

  // Installed models
  const instEl = document.getElementById('installedModels');
  instEl.innerHTML = _installedModels.length ? _installedModels.map(m => \`
    <div class="model-card installed">
      <div class="model-info">
        <div class="model-name">\${escHtml(m)}</div>
        <div class="model-meta">✅ Installed</div>
      </div>
      <div class="model-actions">
        <button class="btn btn-danger btn-sm" onclick="deleteModel('\${escHtml(m)}')">🗑 Delete</button>
      </div>
    </div>
  \`).join('') : '<p style="color:#8b949e;font-size:12px">No models installed</p>';

  // Recommended models
  const recEl = document.getElementById('recommendedModels');
  recEl.innerHTML = recommended.map(r => {
    const installed = _installedModels.includes(r.name);
    return \`
    <div class="model-card \${installed ? 'installed' : ''}" id="mc-\${r.name.replace(/[:.]/g,'_')}">
      <div class="model-info">
        <div class="model-name">\${escHtml(r.name)}</div>
        <div class="model-meta">\${r.size} · \${escHtml(r.best_for)}</div>
        <div class="model-roles">\${(r.roles||[]).map(role => \`<span class="role-tag">\${role}</span>\`).join('')}</div>
        <div class="pull-progress" id="pp-\${r.name.replace(/[:.]/g,'_')}"></div>
      </div>
      <div class="model-actions">
        \${installed
          ? '<span class="install-badge">✓ Installed</span>'
          : \`<button class="btn btn-primary btn-sm" id="btn-\${r.name.replace(/[:.]/g,'_')}" onclick="pullModel('\${escHtml(r.name)}',this)">⬇ Install</button>\`
        }
      </div>
    </div>\`;
  }).join('');
}

function handlePullProgress(name, status, completed, total) {
  const key = name.replace(/[:.]/g,'_');
  const pp = document.getElementById('pp-' + key);
  const btn = document.getElementById('btn-' + key);
  if (!pp) return;
  if (status === 'success' || status === 'done') {
    pp.textContent = '✅ Installed!';
    if (btn) { btn.textContent = '✓'; btn.disabled = true; }
    setTimeout(() => loadModels(), 1000);
  } else if (total > 0) {
    const pct = Math.round((completed / total) * 100);
    pp.textContent = \`⬇ \${status} \${pct}%\`;
  } else {
    pp.textContent = \`⬇ \${status}…\`;
  }
}

function clearEl(el) { if (el) el.innerHTML = ''; }
function clearLog() {
  clearEl(document.getElementById('masterLog'));
  clearEl(document.getElementById('forgeLog'));
  clearEl(document.getElementById('debugLog'));
  clearEl(document.getElementById('evolveLog'));
}

const TYPE_CLASS = {
  agent_start: 'start', agent_done: 'done', agent_error: 'error',
  file_created: 'file', file_modified: 'file',
  build_success: 'build-ok', build_error: 'build-err',
  forge_complete: 'complete', forge_error: 'error',
  log: '', command_run: '', command_output: ''
};

function appendLog(container, event) {
  if (!container) return;
  const div = document.createElement('div');
  const cls = TYPE_CLASS[event.type] || '';
  div.className = 'log-entry ' + cls;
  const agentSpan = \`<span class="agent">[\${event.agent}]</span>\`;
  const icon = event.type === 'file_created' ? '📄 ' : event.type === 'file_modified' ? '✏️ ' :
    event.type === 'build_success' ? '✅ ' : event.type === 'build_error' ? '❌ ' :
    event.type === 'forge_complete' ? '🎉 ' : event.type === 'agent_start' ? '▶ ' :
    event.type === 'agent_done' ? '✔ ' : event.type === 'agent_error' ? '✗ ' : '';
  div.innerHTML = \`\${agentSpan} <span class="msg">\${icon}\${escHtml(event.message)}</span>\`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;

  // Handle findings in evolve tab
  if (event.data && event.data.findings) {
    renderFindings(event.data.findings);
  }
}

function renderFindings(findings) {
  const container = document.getElementById('findings');
  container.innerHTML = '<label style="color:#ffa657;font-size:13px;margin-bottom:8px">Analysis Findings:</label>';
  findings.forEach(f => {
    const div = document.createElement('div');
    div.className = 'finding ' + (f.priority || 'LOW');
    div.innerHTML = \`
      <div class="finding-type">\${f.priority || 'INFO'} · \${f.type || ''}</div>
      <div class="finding-issue">\${escHtml(f.issue || f.message || '')}</div>
      \${f.suggestion ? \`<div class="finding-fix">💡 \${escHtml(f.suggestion)}</div>\` : ''}
      \${f.file ? \`<div style="color:#8b949e;font-size:11px;margin-top:4px">📄 \${escHtml(f.file)}</div>\` : ''}
    \`;
    container.appendChild(div);
  });
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

window.addEventListener('message', e => {
  const { command, data } = e.data;
  const master = document.getElementById('masterLog');
  const bar = document.getElementById('progressBar');

  if (command === 'event') {
    appendLog(activeLog, data);
    appendLog(master, data);
  } else if (command === 'streamStart') {
    bar.classList.add('running');
    setStatus('running', data.title || 'Working…');
  } else if (command === 'streamEnd') {
    bar.classList.remove('running');
    bar.style.width = '0%';
    setStatus('ok', 'Idle');
  } else if (command === 'error') {
    appendLog(activeLog, { type: 'agent_error', agent: 'extension', message: data.message });
    bar.classList.remove('running');
    setStatus('err', 'Error');
  } else if (command === 'status') {
    const ok = data.ollama_online;
    const count = (data.models || []).length;
    setStatus(ok ? 'ok' : 'err', ok ? \`Ollama online · \${count} model\${count!==1?'s':''}\` : 'Ollama offline');
    document.getElementById('statusBadge').textContent = data.status;
    document.getElementById('statusBadge').style.background = ok ? '#238636' : '#b62324';
  } else if (command === 'modelsData') {
    renderModelTab(data);
  } else if (command === 'pullProgress') {
    handlePullProgress(data.name, data.status, data.completed || 0, data.total || 0);
  } else if (command === 'modelConfigUpdated') {
    _currentConfig = data;
  }
});

function setStatus(state, text) {
  const dot = document.getElementById('statusDot');
  document.getElementById('statusText').textContent = text;
  dot.style.background = state === 'ok' ? '#3fb950' : state === 'err' ? '#f85149' : '#ffa657';
}

// Check status on load
setTimeout(() => checkStatus(), 500);
</script>
</body>
</html>`;
  }
}

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
  <div class="tab" onclick="switchTab('log')">📋 Log</div>
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

<div class="status-bar">
  <span class="status-dot" id="statusDot" style="background:#8b949e"></span>
  <span id="statusText">Connecting…</span>
</div>

<script>
const vscode = acquireVsCodeApi();
let activeLog = document.getElementById('forgeLog');

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelector(\`.tab:nth-child(\${['forge','debug','evolve','log'].indexOf(tab)+1})\`).classList.add('active');
  document.getElementById('panel-' + tab).classList.add('active');
  activeLog = document.getElementById(tab + 'Log') || document.getElementById('masterLog');
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
    setStatus(ok ? 'ok' : 'err', ok ? \`Ollama online · \${data.models.length} models\` : 'Ollama offline');
    document.getElementById('statusBadge').textContent = data.status;
    document.getElementById('statusBadge').style.background = ok ? '#238636' : '#b62324';
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

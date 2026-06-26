import * as vscode from "vscode";
import { AgentPanel } from "./panels/AgentPanel";
import { BackendClient } from "./services/BackendClient";

let client: BackendClient;

export function activate(context: vscode.ExtensionContext): void {
  const cfg = vscode.workspace.getConfiguration("autoforge");
  const backendUrl: string = cfg.get("backendUrl") ?? "http://localhost:8003";
  client = new BackendClient(backendUrl);

  // Refresh client when config changes
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("autoforge.backendUrl")) {
        const newUrl = vscode.workspace
          .getConfiguration("autoforge")
          .get<string>("backendUrl", "http://localhost:8003");
        client = new BackendClient(newUrl);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("autoforge.openPanel", () => {
      AgentPanel.createOrShow(context.extensionUri, client);
    }),

    vscode.commands.registerCommand("autoforge.forgeProject", () => {
      AgentPanel.createOrShow(context.extensionUri, client);
    }),

    vscode.commands.registerCommand("autoforge.debugBuild", () => {
      AgentPanel.createOrShow(context.extensionUri, client);
    }),

    vscode.commands.registerCommand("autoforge.runEvolution", () => {
      AgentPanel.createOrShow(context.extensionUri, client);
    }),

    vscode.commands.registerCommand("autoforge.checkStatus", async () => {
      const health = await client.checkHealth();
      const msg = health.ollama_online
        ? `AutoForge AI: Ollama online — ${health.models.length} model(s) available`
        : "AutoForge AI: Ollama is offline. Start Ollama first.";
      health.ollama_online
        ? vscode.window.showInformationMessage(msg)
        : vscode.window.showWarningMessage(msg);
    })
  );

  // Show status bar button
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.text = "$(robot) AutoForge";
  statusBar.command = "autoforge.openPanel";
  statusBar.tooltip = "Open AutoForge AI Panel";
  statusBar.show();
  context.subscriptions.push(statusBar);
}

export function deactivate(): void {}

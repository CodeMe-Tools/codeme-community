/**
 * Codeme VS Code Thin-Client Extension.
 *
 * Implements Directive Revision 7, Section 25 (IDE Integration):
 * - Problems-panel diagnostics from CLI stderr/stdout.
 * - Native Quick Fix code actions.
 * - Optional save-time auto repairs.
 * - Thin client: no duplicate repair engine in editor extensions.
 */

import * as vscode from "vscode";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

let diagnosticCollection: vscode.DiagnosticCollection;

export function activate(context: vscode.ExtensionContext) {
  diagnosticCollection = vscode.languages.createDiagnosticCollection("codeme");
  context.subscriptions.push(diagnosticCollection);

  // Register Quick Fix provider
  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      ["python", "javascript", "typescript", "swift"],
      new CodemeQuickFixProvider(),
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
    )
  );

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand("codeme.syntax.check", async () => {
      const editor = vscode.window.activeTextEditor;
      if (editor) {
        await runEngineOnFile("codeme-syntax", editor.document.uri, false);
      }
    }),
    vscode.commands.registerCommand("codeme.syntax.fix", async () => {
      const editor = vscode.window.activeTextEditor;
      if (editor) {
        await runEngineOnFile("codeme-syntax", editor.document.uri, true);
        await editor.document.reload();
      }
    }),
    vscode.commands.registerCommand("codeme.quality.check", async () => {
      const editor = vscode.window.activeTextEditor;
      if (editor) {
        await runEngineOnFile("codeme-quality", editor.document.uri, false);
      }
    }),
    vscode.commands.registerCommand("codeme.quality.fix", async () => {
      const editor = vscode.window.activeTextEditor;
      if (editor) {
        await runEngineOnFile("codeme-quality", editor.document.uri, true);
        await editor.document.reload();
      }
    }),
    vscode.commands.registerCommand("codeme.fixLoop", async () => {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
      if (workspaceFolder) {
        await runFixLoop(workspaceFolder);
      }
    })
  );

  // Save-time auto-fix
  context.subscriptions.push(
    vscode.workspace.onWillSaveTextDocument(async (event) => {
      const config = vscode.workspace.getConfiguration("codeme");
      if (config.get<boolean>("autoFixOnSave", false)) {
        event.waitUntil(runEngineOnFile("codeme-syntax", event.document.uri, true));
      }
    })
  );

  // Document change / save diagnostic updates
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (document) => {
      const config = vscode.workspace.getConfiguration("codeme");
      if (config.get<boolean>("enableDiagnostics", true)) {
        await runEngineOnFile("codeme-syntax", document.uri, false);
      }
    })
  );
}

async function runEngineOnFile(binaryName: string, uri: vscode.Uri, fix: boolean) {
  const filePath = uri.fsPath;
  const args = ["run", "--file", filePath];
  if (fix) {
    args.push("--fix");
  }

  try {
    await execFileAsync(binaryName, args);
    diagnosticCollection.delete(uri);
  } catch (error: any) {
    const output = (error.stderr || "") + "\n" + (error.stdout || "");
    const diags = parseDiagnostics(output, uri);
    diagnosticCollection.set(uri, diags);
  }
}

async function runFixLoop(cwd: string) {
  try {
    await execFileAsync("codeme-skills", ["fix-loop", "--repo", cwd]);
    diagnosticCollection.clear();
    vscode.window.showInformationMessage("Codeme: Fix loop passed cleanly.");
  } catch (error: any) {
    vscode.window.showErrorMessage("Codeme: Fix loop encountered unrepairable diagnostics.");
  }
}

function parseDiagnostics(output: string, currentUri: vscode.Uri): vscode.Diagnostic[] {
  const results: vscode.Diagnostic[] = [];
  const lines = output.split("\n");
  const regex = /^\[(CDM-[A-Z0-9-]+)\]\s*(?:\[([A-Z]+)\]\s*)?(?:([^:]+):(\d+):(\d+):\s*)?(.*)$/;

  for (const line of lines) {
    const match = regex.exec(line.trim());
    if (match) {
      const [, code, sevStr, , lineStr, colStr, msg] = match;
      const lineNum = Math.max(0, parseInt(lineStr || "1", 10) - 1);
      const colNum = Math.max(0, parseInt(colStr || "1", 10) - 1);
      const range = new vscode.Range(lineNum, colNum, lineNum, colNum + 10);

      let severity = vscode.DiagnosticSeverity.Error;
      if (sevStr?.toUpperCase() === "WARNING") {
        severity = vscode.DiagnosticSeverity.Warning;
      } else if (sevStr?.toUpperCase() === "INFO") {
        severity = vscode.DiagnosticSeverity.Information;
      }

      const diag = new vscode.Diagnostic(range, `[${code}] ${msg}`, severity);
      diag.code = code;
      diag.source = "Codeme";
      results.push(diag);
    }
  }

  return results;
}

export class CodemeQuickFixProvider implements vscode.CodeActionProvider {
  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];

    for (const diag of context.diagnostics) {
      if (diag.source === "Codeme") {
        const action = new vscode.CodeAction(
          `Apply Codeme Deterministic Fix for ${diag.code}`,
          vscode.CodeActionKind.QuickFix
        );
        action.command = {
          command: "codeme.syntax.fix",
          title: "Run Codeme Syntax Repair",
        };
        action.diagnostics = [diag];
        action.isPreferred = true;
        actions.push(action);
      }
    }

    return actions;
  }
}

export function deactivate() {
  if (diagnosticCollection) {
    diagnosticCollection.clear();
    diagnosticCollection.dispose();
  }
}

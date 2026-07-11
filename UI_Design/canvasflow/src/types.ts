export type ThemeName = "Ocean" | "Mint" | "Purple" | "Rose" | "Orange";
export type ThemeMode = "light" | "dark";

export interface ThemeColors {
  primary: string;
  success: string;
  warning: string;
  danger: string;
  background: string;
  surface: string;
  border: string;
  text: string;
  secondaryText: string;
}

export type NodeType = "AI" | "Database" | "HTTP" | "Condition" | "Logic" | "End";

export interface NodeSocket {
  id: string;
  name: string;
  type: "input" | "output";
  dataType: "string" | "boolean" | "number" | "any";
}

export interface NodeConfig {
  [key: string]: any;
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  name: string;
  subType: string; // e.g. "chatgpt", "translator", "summarizer", "kv-store", "api-request", "if-else", "user-input", "log-viewer"
  x: number;
  y: number;
  width: number;
  height: number;
  inputs: NodeSocket[];
  outputs: NodeSocket[];
  config: NodeConfig;
  status: "idle" | "running" | "success" | "warning" | "error";
  errorMessage?: string;
  outputData?: any;
}

export interface NodeConnection {
  id: string;
  sourceNodeId: string;
  sourceSocketId: string;
  targetNodeId: string;
  targetSocketId: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  connections: NodeConnection[];
}

export interface ExecutionLog {
  id: string;
  timestamp: string;
  type: "info" | "success" | "warning" | "error";
  nodeId?: string;
  nodeName?: string;
  message: string;
}

export interface AIAssistantMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  suggestedAction?: {
    type: "create_nodes" | "create_workflow";
    payload: any;
  };
}

import React, { useState, useEffect } from "react";
import { 
  WorkflowNode, 
  NodeConnection, 
  ThemeName, 
  ThemeMode, 
  ExecutionLog, 
  NodeType,
  NodeSocket
} from "./types";
import { getThemeColors } from "./theme";
import Toolbar from "./components/Toolbar";
import Sidebar from "./components/Sidebar";
import Canvas from "./components/Canvas";
import Inspector from "./components/Inspector";
import AIAssistant from "./components/AIAssistant";

// Default pre-populated workflow node items
const initialNodes: WorkflowNode[] = [
  {
    id: "node-input",
    type: "Logic",
    name: "User Text Input",
    subType: "user-input",
    x: 100,
    y: 180,
    width: 220,
    height: 140,
    inputs: [],
    outputs: [{ id: "output-text", name: "Text Output", type: "output", dataType: "string" }],
    config: { value: "Artificial Intelligence transforms complex node workflows into intuitive visual maps." },
    status: "idle"
  },
  {
    id: "node-ai",
    type: "AI",
    name: "🤖 AI Summarizer",
    subType: "summarizer",
    x: 420,
    y: 180,
    width: 220,
    height: 180,
    inputs: [{ id: "input-text", name: "Bulk Content", type: "input", dataType: "string" }],
    outputs: [{ id: "output-text", name: "Summary", type: "output", dataType: "string" }],
    config: { wordLimit: 15, text: "" },
    status: "idle"
  },
  {
    id: "node-log",
    type: "End",
    name: "📺 Log Terminal",
    subType: "log-viewer",
    x: 740,
    y: 180,
    width: 220,
    height: 120,
    inputs: [{ id: "input-data", name: "Data Feed", type: "input", dataType: "any" }],
    outputs: [],
    config: {},
    status: "idle"
  }
];

const initialConnections: NodeConnection[] = [
  {
    id: "conn-1",
    sourceNodeId: "node-input",
    sourceSocketId: "output-text",
    targetNodeId: "node-ai",
    targetSocketId: "input-text"
  },
  {
    id: "conn-2",
    sourceNodeId: "node-ai",
    sourceSocketId: "output-text",
    targetNodeId: "node-log",
    targetSocketId: "input-data"
  }
];

export default function App() {
  const [nodes, setNodes] = useState<WorkflowNode[]>(initialNodes);
  const [connections, setConnections] = useState<NodeConnection[]>(initialConnections);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  
  const [workflowName, setWorkflowName] = useState("CanvasFlow Workspace");
  const [themeName, setThemeName] = useState<ThemeName>("Ocean");
  const [themeMode, setThemeMode] = useState<ThemeMode>("dark");
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);

  // Runtime state controllers
  const [isExecuting, setIsExecuting] = useState(false);
  const [executingNodeId, setExecutingNodeId] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [runHistory, setRunHistory] = useState<{ id: string; timestamp: string; status: string; workflowName: string }[]>([]);

  const colors = getThemeColors(themeName, themeMode);

  // Add system-level initialization log
  useEffect(() => {
    addLog("info", "Workspace system loaded successfully. Apple iOS 26 Liquid Glass initialized.");
  }, []);

  const addLog = (type: "info" | "success" | "warning" | "error", message: string, nodeId?: string, nodeName?: string) => {
    const newLog: ExecutionLog = {
      id: Math.random().toString(),
      timestamp: new Date().toLocaleTimeString(),
      type,
      nodeId,
      nodeName,
      message
    };
    setLogs((prev) => [newLog, ...prev]);
  };

  // Node position manager
  const handleUpdateNodePosition = (nodeId: string, x: number, y: number) => {
    setNodes((prev) => 
      prev.map((n) => (n.id === nodeId ? { ...n, x, y } : n))
    );
  };

  // Connection manager
  const handleAddConnection = (
    sourceNodeId: string,
    sourceSocketId: string,
    targetNodeId: string,
    targetSocketId: string
  ) => {
    // Prevent duplicate connections targeting the same target socket
    const exists = connections.some(
      (c) => c.targetNodeId === targetNodeId && c.targetSocketId === targetSocketId
    );
    if (exists) {
      addLog("warning", `Input socket already has an active connection link.`);
      return;
    }

    const newConn: NodeConnection = {
      id: `conn-${Math.random().toString()}`,
      sourceNodeId,
      sourceSocketId,
      targetNodeId,
      targetSocketId
    };

    setConnections((prev) => [...prev, newConn]);
    addLog("info", `Linked node socket connection successfully.`);
  };

  const handleRemoveConnection = (connectionId: string) => {
    setConnections((prev) => prev.filter((c) => c.id !== connectionId));
    addLog("info", `Removed workspace connection link.`);
  };

  // Node additions and deletions
  const handleRemoveNode = (nodeId: string) => {
    setNodes((prev) => prev.filter((n) => n.id !== nodeId));
    setConnections((prev) => prev.filter((c) => c.sourceNodeId !== nodeId && c.targetNodeId !== nodeId));
    if (selectedNodeId === nodeId) {
      setSelectedNodeId(null);
    }
    addLog("info", `Removed node from workspace.`);
  };

  const handleAddNode = (subType: string, customProps?: Partial<WorkflowNode>) => {
    // Generate sockets based on subtypes
    let inputs: NodeSocket[] = [];
    let outputs: NodeSocket[] = [];
    let name = "Node";
    let type: NodeType = "Logic";
    let config: any = {};

    switch (subType) {
      case "chatgpt":
        name = "🤖 ChatGPT Agent";
        type = "AI";
        inputs = [{ id: "input-text", name: "Prompt Input", type: "input", dataType: "string" }];
        outputs = [{ id: "output-text", name: "AI Response", type: "output", dataType: "string" }];
        config = { prompt: "", systemInstruction: "You are a concise orchestrator.", temperature: 0.7 };
        break;
      case "translator":
        name = "✨ AI Translator";
        type = "AI";
        inputs = [{ id: "input-text", name: "Source Text", type: "input", dataType: "string" }];
        outputs = [{ id: "output-text", name: "Translation", type: "output", dataType: "string" }];
        config = { targetLanguage: "Spanish", text: "" };
        break;
      case "summarizer":
        name = "📝 AI Summarizer";
        type = "AI";
        inputs = [{ id: "input-text", name: "Bulk Content", type: "input", dataType: "string" }];
        outputs = [{ id: "output-text", name: "Summary", type: "output", dataType: "string" }];
        config = { wordLimit: 25, text: "" };
        break;
      case "kv-store":
        name = "🗄️ Key-Value Store";
        type = "Database";
        inputs = [{ id: "input-value", name: "Record Value", type: "input", dataType: "string" }];
        outputs = [{ id: "output-status", name: "Result Status", type: "output", dataType: "string" }];
        config = { operation: "write", key: "backup_key", value: "" };
        break;
      case "api-request":
        name = "🌐 HTTP API Request";
        type = "HTTP";
        inputs = [];
        outputs = [{ id: "output-json", name: "Response JSON", type: "output", dataType: "any" }];
        config = { method: "GET", url: "https://api.example.com/feed" };
        break;
      case "if-else":
        name = "🔀 If-Else Switch";
        type = "Condition";
        inputs = [{ id: "input-cond", name: "Boolean Input", type: "input", dataType: "boolean" }];
        outputs = [
          { id: "output-true", name: "If True", type: "output", dataType: "any" },
          { id: "output-false", name: "If False", type: "output", dataType: "any" }
        ];
        config = { condition: "true" };
        break;
      case "user-input":
        name = "✍️ User Text Input";
        type = "Logic";
        inputs = [];
        outputs = [{ id: "output-text", name: "Text Output", type: "output", dataType: "string" }];
        config = { value: "Enter your custom string values here..." };
        break;
      case "log-viewer":
        name = "📺 Log Terminal";
        type = "End";
        inputs = [{ id: "input-data", name: "Data Feed", type: "input", dataType: "any" }];
        outputs = [];
        config = {};
        break;
    }

    const spawnX = 250 + Math.random() * 80;
    const spawnY = 150 + Math.random() * 80;

    const newNode: WorkflowNode = {
      id: `node-${Math.random().toString().substring(2, 9)}`,
      type,
      name,
      subType,
      x: spawnX,
      y: spawnY,
      width: 220,
      height: 140,
      inputs,
      outputs,
      config,
      status: "idle",
      ...customProps
    };

    setNodes((prev) => [...prev, newNode]);
    addLog("info", `Deployed ${newNode.name} node onto canvas.`);
  };

  // Node configurations field updates
  const handleUpdateNodeConfig = (nodeId: string, updatedConfig: any) => {
    setNodes((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, config: updatedConfig } : n))
    );
  };

  // Execute single Node standalone (and fetch dynamic input wires first)
  const runSingleNode = async (nodeId: string) => {
    const node = nodes.find(n => n.id === nodeId);
    if (!node) return;

    setExecutingNodeId(nodeId);
    setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, status: "running" } : n));
    addLog("info", `Beginning computation sequence for: ${node.name}`, nodeId, node.name);

    // Resolve inputs from upstream nodes
    const resolvedInputs: Record<string, any> = {};
    node.inputs.forEach((inputSocket) => {
      // Find connection targeting this socket
      const connection = connections.find(c => c.targetNodeId === nodeId && c.targetSocketId === inputSocket.id);
      if (connection) {
        const sourceNode = nodes.find(n => n.id === connection.sourceNodeId);
        if (sourceNode && sourceNode.outputData) {
          resolvedInputs[inputSocket.id] = sourceNode.outputData;
        }
      }
    });

    try {
      const response = await fetch("/api/run-node", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nodeType: node.type,
          subType: node.subType,
          config: node.config,
          inputs: resolvedInputs
        })
      });

      if (!response.ok) {
        throw new Error(`Server returned HTTP code ${response.status}`);
      }

      const resData = await response.json();

      if (resData.status === "success") {
        setNodes(prev => prev.map(n => n.id === nodeId ? { 
          ...n, 
          status: "success", 
          outputData: resData.output 
        } : n));
        addLog("success", `Completed computation for: ${node.name}. Output length: ${String(resData.output).length} chars.`, nodeId, node.name);
      } else {
        throw new Error(resData.message || "Failed execution");
      }
    } catch (err: any) {
      console.error(err);
      setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, status: "error", errorMessage: err.message } : n));
      addLog("error", `Computation failed for ${node.name}: ${err.message}`, nodeId, node.name);
    } finally {
      setExecutingNodeId(null);
    }
  };

  // Run whole workflow topologically!
  const handleRunWorkflow = async () => {
    if (isExecuting) return;
    setIsExecuting(true);
    addLog("info", "Starting pipeline topological sorting sequence...");

    // Set all nodes to idle / prepare execution states
    setNodes(prev => prev.map(n => ({ ...n, status: "idle", outputData: undefined })));

    // 1. Build topological levels of execution:
    // Simple topological sorting:
    // Find nodes that have no unresolved upstream dependencies.
    const visited = new Set<string>();
    const executionOrder: WorkflowNode[] = [];

    // Helper to traverse node dependencies
    const visit = (node: WorkflowNode) => {
      if (visited.has(node.id)) return;
      
      // Get all upstream nodes (dependencies)
      const incomingConnections = connections.filter(c => c.targetNodeId === node.id);
      incomingConnections.forEach((conn) => {
        const parentNode = nodes.find(n => n.id === conn.sourceNodeId);
        if (parentNode) {
          visit(parentNode);
        }
      });

      visited.add(node.id);
      executionOrder.push(node);
    };

    nodes.forEach(n => visit(n));

    addLog("info", `Topological sort computed. Sequence length: ${executionOrder.length} levels.`);

    let sessionSuccess = true;

    // 2. Execute sequentially
    for (const nodeToRun of executionOrder) {
      setExecutingNodeId(nodeToRun.id);
      setNodes(prev => prev.map(n => n.id === nodeToRun.id ? { ...n, status: "running" } : n));
      
      // Fetch dynamic upstream payloads
      const resolvedInputs: Record<string, any> = {};
      nodeToRun.inputs.forEach((inputSocket) => {
        const conn = connections.find(c => c.targetNodeId === nodeToRun.id && c.targetSocketId === inputSocket.id);
        if (conn) {
          const sourceNodeState = nodes.find(n => n.id === conn.sourceNodeId);
          // Fallback if not evaluated yet, fetch from outputs
          if (sourceNodeState && sourceNodeState.outputData) {
            resolvedInputs[inputSocket.id] = sourceNodeState.outputData;
          }
        }
      });

      // Special user-input node uses direct config value
      if (nodeToRun.subType === "user-input") {
        resolvedInputs["value"] = nodeToRun.config.value;
      }

      try {
        addLog("info", `Executing visual sequence cell: ${nodeToRun.name}`, nodeToRun.id, nodeToRun.name);
        
        // Artificial micro-delay to simulate flowing animation
        await new Promise(r => setTimeout(r, 800));

        const response = await fetch("/api/run-node", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            nodeType: nodeToRun.type,
            subType: nodeToRun.subType,
            config: nodeToRun.config,
            inputs: resolvedInputs
          })
        });

        if (!response.ok) {
          throw new Error(`Server returned HTTP code ${response.status}`);
        }

        const resData = await response.json();

        if (resData.status === "success") {
          // Update the localized node state in the list
          setNodes(prev => prev.map(n => n.id === nodeToRun.id ? { 
            ...n, 
            status: "success", 
            outputData: resData.output 
          } : n));
          
          // Propagate into actual nodes variable array for downstream lookup
          nodes.forEach(n => {
            if (n.id === nodeToRun.id) {
              n.outputData = resData.output;
              n.status = "success";
            }
          });

          addLog("success", `Dynamic node [${nodeToRun.name}] success: data cached.`, nodeToRun.id, nodeToRun.name);
        } else {
          throw new Error(resData.message || "Failed node execution step.");
        }
      } catch (err: any) {
        console.error(err);
        setNodes(prev => prev.map(n => n.id === nodeToRun.id ? { ...n, status: "error" } : n));
        addLog("error", `Execution halted: ${err.message}`, nodeToRun.id, nodeToRun.name);
        sessionSuccess = false;
        break;
      }
    }

    setIsExecuting(false);
    setExecutingNodeId(null);

    // Save history
    const historyItem = {
      id: Math.random().toString(),
      timestamp: new Date().toLocaleTimeString(),
      status: sessionSuccess ? "completed" : "failed",
      workflowName: workflowName
    };
    setRunHistory(prev => [historyItem, ...prev]);

    if (sessionSuccess) {
      addLog("success", "🎉 Workflow pipeline run completed successfully.");
    } else {
      addLog("error", "⚠️ Workflow pipeline execution failed. Please check debug consoles.");
    }
  };

  // Clears active canvas
  const handleClearCanvas = () => {
    if (window.confirm("Are you sure you want to completely clear the workspace canvas?")) {
      setNodes([]);
      setConnections([]);
      setSelectedNodeId(null);
      addLog("warning", "Workspace canvas cleared.");
    }
  };

  // Loads prebuilt workflow setups
  const handleLoadTemplate = (templateId: string) => {
    setSelectedNodeId(null);

    if (templateId === "translator-pipe") {
      setNodes([
        {
          id: "t-input",
          type: "Logic",
          name: "Original Source input",
          subType: "user-input",
          x: 100,
          y: 200,
          width: 220,
          height: 140,
          inputs: [],
          outputs: [{ id: "output-text", name: "Text Output", type: "output", dataType: "string" }],
          config: { value: "Welcome to CanvasFlow, a world-class AI node playground." },
          status: "idle"
        },
        {
          id: "t-ai",
          type: "AI",
          name: "✨ AI Translator",
          subType: "translator",
          x: 420,
          y: 200,
          width: 220,
          height: 140,
          inputs: [{ id: "input-text", name: "Source Text", type: "input", dataType: "string" }],
          outputs: [{ id: "output-text", name: "Translation", type: "output", dataType: "string" }],
          config: { targetLanguage: "Spanish", text: "" },
          status: "idle"
        },
        {
          id: "t-log",
          type: "End",
          name: "📺 Log Terminal",
          subType: "log-viewer",
          x: 740,
          y: 200,
          width: 220,
          height: 120,
          inputs: [{ id: "input-data", name: "Data Feed", type: "input", dataType: "any" }],
          outputs: [],
          config: {},
          status: "idle"
        }
      ]);
      setConnections([
        {
          id: "tc-1",
          sourceNodeId: "t-input",
          sourceSocketId: "output-text",
          targetNodeId: "t-ai",
          targetSocketId: "input-text"
        },
        {
          id: "tc-2",
          sourceNodeId: "t-ai",
          sourceSocketId: "output-text",
          targetNodeId: "t-log",
          targetSocketId: "input-data"
        }
      ]);
      addLog("info", "Loaded Global Translation Pipeline preset.");
    } else if (templateId === "news-summary") {
      setNodes([
        {
          id: "n-api",
          type: "HTTP",
          name: "🌐 Fetch Latest Articles",
          subType: "api-request",
          x: 100,
          y: 180,
          width: 220,
          height: 140,
          inputs: [],
          outputs: [{ id: "output-json", name: "Response JSON", type: "output", dataType: "any" }],
          config: { method: "GET", url: "https://api.example.com/v1/news" },
          status: "idle"
        },
        {
          id: "n-ai",
          type: "AI",
          name: "📝 AI Summarizer",
          subType: "summarizer",
          x: 420,
          y: 180,
          width: 220,
          height: 180,
          inputs: [{ id: "input-text", name: "Bulk Content", type: "input", dataType: "string" }],
          outputs: [{ id: "output-text", name: "Summary", type: "output", dataType: "string" }],
          config: { wordLimit: 20, text: "" },
          status: "idle"
        },
        {
          id: "n-db",
          type: "Database",
          name: "🗄️ Save Backup Copy",
          subType: "kv-store",
          x: 740,
          y: 180,
          width: 220,
          height: 140,
          inputs: [{ id: "input-value", name: "Record Value", type: "input", dataType: "string" }],
          outputs: [{ id: "output-status", name: "Result Status", type: "output", dataType: "string" }],
          config: { operation: "write", key: "summarized_news_v1", value: "" },
          status: "idle"
        }
      ]);
      setConnections([
        {
          id: "nc-1",
          sourceNodeId: "n-api",
          sourceSocketId: "output-json",
          targetNodeId: "n-ai",
          targetSocketId: "input-text"
        },
        {
          id: "nc-2",
          sourceNodeId: "n-ai",
          sourceSocketId: "output-text",
          targetNodeId: "n-db",
          targetSocketId: "input-value"
        }
      ]);
      addLog("info", "Loaded News-Summarizer DB Sync template.");
    } else if (templateId === "conditional-agent") {
      setNodes([
        {
          id: "c-input",
          type: "Logic",
          name: "Condition Text State",
          subType: "user-input",
          x: 80,
          y: 200,
          width: 220,
          height: 140,
          inputs: [],
          outputs: [{ id: "output-text", name: "Text Output", type: "output", dataType: "string" }],
          config: { value: "Explain why glass styling represents future design." },
          status: "idle"
        },
        {
          id: "c-switch",
          type: "Condition",
          name: "🔀 Filter Switch",
          subType: "if-else",
          x: 370,
          y: 200,
          width: 220,
          height: 160,
          inputs: [{ id: "input-cond", name: "Boolean Input", type: "input", dataType: "boolean" }],
          outputs: [
            { id: "output-true", name: "If True", type: "output", dataType: "any" },
            { id: "output-false", name: "If False", type: "output", dataType: "any" }
          ],
          config: { condition: "true" },
          status: "idle"
        },
        {
          id: "c-ai",
          type: "AI",
          name: "🤖 ChatGPT Agent",
          subType: "chatgpt",
          x: 660,
          y: 120,
          width: 220,
          height: 180,
          inputs: [{ id: "input-text", name: "Prompt Input", type: "input", dataType: "string" }],
          outputs: [{ id: "output-text", name: "AI Response", type: "output", dataType: "string" }],
          config: { prompt: "Explain modern glass styling in 2 sentences.", systemInstruction: "Be creative.", temperature: 0.9 },
          status: "idle"
        },
        {
          id: "c-log",
          type: "End",
          name: "📺 Log Terminal",
          subType: "log-viewer",
          x: 950,
          y: 200,
          width: 220,
          height: 120,
          inputs: [{ id: "input-data", name: "Data Feed", type: "input", dataType: "any" }],
          outputs: [],
          config: {},
          status: "idle"
        }
      ]);
      setConnections([
        {
          id: "cc-1",
          sourceNodeId: "c-input",
          sourceSocketId: "output-text",
          targetNodeId: "c-switch",
          targetSocketId: "input-cond"
        },
        {
          id: "cc-2",
          sourceNodeId: "c-switch",
          sourceSocketId: "output-true",
          targetNodeId: "c-ai",
          targetSocketId: "input-text"
        },
        {
          id: "cc-3",
          sourceNodeId: "c-ai",
          sourceSocketId: "output-text",
          targetNodeId: "c-log",
          targetSocketId: "input-data"
        }
      ]);
      addLog("info", "Loaded Conditional Chat Branching setup.");
    }
  };

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) || null;

  return (
    <div 
      style={{ backgroundColor: colors.background }}
      className="flex flex-col h-screen w-screen overflow-hidden font-sans transition-all duration-300"
    >
      {/* 1. Header Toolbar */}
      <Toolbar
        workflowName={workflowName}
        setWorkflowName={setWorkflowName}
        themeName={themeName}
        setThemeName={setThemeName}
        themeMode={themeMode}
        setThemeMode={setThemeMode}
        onRunWorkflow={handleRunWorkflow}
        isExecuting={isExecuting}
        onToggleAssistant={() => setIsAssistantOpen(!isAssistantOpen)}
        isAssistantOpen={isAssistantOpen}
        onClearCanvas={handleClearCanvas}
      />

      {/* 2. Main Workspace Row (Three-column layout) */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Left column - Node palette drawer */}
        <Sidebar
          themeName={themeName}
          themeMode={themeMode}
          onAddNode={handleAddNode}
          onLoadTemplate={handleLoadTemplate}
          runHistory={runHistory}
          onClearHistory={() => setRunHistory([])}
        />

        {/* Center column - Draggable canvas viewport */}
        <Canvas
          nodes={nodes}
          connections={connections}
          selectedNodeId={selectedNodeId}
          onSelectNode={setSelectedNodeId}
          onUpdateNodePosition={handleUpdateNodePosition}
          onAddConnection={handleAddConnection}
          onRemoveConnection={handleRemoveConnection}
          onRemoveNode={handleRemoveNode}
          onRunSingleNode={runSingleNode}
          themeName={themeName}
          themeMode={themeMode}
          isExecuting={isExecuting}
          executingNodeId={executingNodeId}
        />

        {/* Right column - Property & output logs inspector */}
        <Inspector
          selectedNode={selectedNode}
          onUpdateNodeConfig={handleUpdateNodeConfig}
          onRunSingleNode={runSingleNode}
          onDeselect={() => setSelectedNodeId(null)}
          themeName={themeName}
          themeMode={themeMode}
          logs={logs}
        />

        {/* Slide-out floating AI helper Drawer */}
        <AIAssistant
          isOpen={isAssistantOpen}
          onClose={() => setIsAssistantOpen(false)}
          themeName={themeName}
          themeMode={themeMode}
          workflowContext={nodes}
          onAddCustomNode={(nodeData) => handleAddNode(nodeData.subType, nodeData)}
        />
      </div>
    </div>
  );
}

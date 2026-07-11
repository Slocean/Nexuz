import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = 3000;

app.use(express.json());

// Lazy-initialize Gemini client to prevent crash on startup if key is missing
let aiClient: GoogleGenAI | null = null;

function getAiClient(): GoogleGenAI {
  if (!aiClient) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey || apiKey === "MY_GEMINI_API_KEY") {
      console.warn("GEMINI_API_KEY environment variable is not configured correctly. Using simulated AI fallback.");
      throw new Error("API_KEY_MISSING");
    }
    aiClient = new GoogleGenAI({
      apiKey: apiKey,
      httpOptions: {
        headers: {
          "User-Agent": "aistudio-build",
        },
      },
    });
  }
  return aiClient;
}

// 1. Run Node execution endpoint (using live Gemini model)
app.post("/api/run-node", async (req, res) => {
  const { nodeType, subType, config, inputs } = req.body;

  try {
    if (subType === "chatgpt") {
      const prompt = config.prompt || "Hello! Introduce yourself briefly.";
      const systemInstruction = config.systemInstruction || "You are a helpful assistant.";
      const temperature = parseFloat(config.temperature) || 0.7;

      try {
        const ai = getAiClient();
        const response = await ai.models.generateContent({
          model: "gemini-3.5-flash",
          contents: prompt,
          config: {
            systemInstruction,
            temperature,
          },
        });

        return res.json({
          status: "success",
          output: response.text || "(No response generated)",
        });
      } catch (err: any) {
        if (err.message === "API_KEY_MISSING") {
          // Simulated fallback if key is missing
          return res.json({
            status: "success",
            output: `[Demo Fallback Mode] Generated response for: "${prompt}" (Please configure GEMINI_API_KEY in Secrets panel to use live model)`,
          });
        }
        throw err;
      }
    }

    if (subType === "translator") {
      const textToTranslate = inputs.text || config.text || "Hello world";
      const targetLang = config.targetLanguage || "Spanish";

      try {
        const ai = getAiClient();
        const response = await ai.models.generateContent({
          model: "gemini-3.5-flash",
          contents: `Translate the following text into ${targetLang}. Only return the translation, nothing else.\n\nText: "${textToTranslate}"`,
          config: {
            temperature: 0.3,
          },
        });

        return res.json({
          status: "success",
          output: (response.text || "").trim(),
        });
      } catch (err: any) {
        if (err.message === "API_KEY_MISSING") {
          return res.json({
            status: "success",
            output: `[Demo Translation Fallback: Target language ${targetLang}] translated text: "${textToTranslate}"`,
          });
        }
        throw err;
      }
    }

    if (subType === "summarizer") {
      const textToSummarize = inputs.text || config.text || "Long text to summarize...";
      const wordCount = config.wordLimit || 30;

      try {
        const ai = getAiClient();
        const response = await ai.models.generateContent({
          model: "gemini-3.5-flash",
          contents: `Summarize the following text in under ${wordCount} words:\n\n"${textToSummarize}"`,
        });

        return res.json({
          status: "success",
          output: (response.text || "").trim(),
        });
      } catch (err: any) {
        if (err.message === "API_KEY_MISSING") {
          return res.json({
            status: "success",
            output: `[Demo Summary Fallback: Limit ${wordCount} words] Summarized: ${textToSummarize.substring(0, 50)}...`,
          });
        }
        throw err;
      }
    }

    // HTTP trigger simulator
    if (subType === "api-request") {
      const url = config.url || "https://api.example.com/data";
      const method = config.method || "GET";

      // Simulate network request
      return res.json({
        status: "success",
        output: JSON.stringify({
          statusCode: 200,
          statusText: "OK",
          timestamp: new Date().toISOString(),
          requestedUrl: url,
          requestMethod: method,
          data: {
            users: 5,
            active: true,
            payload: "Dynamic server JSON data simulated successfully",
          },
        }, null, 2),
      });
    }

    // Database simulated read/write
    if (subType === "kv-store") {
      const operation = config.operation || "write";
      const key = config.key || "myKey";
      const val = inputs.value || config.value || "DefaultValue";

      return res.json({
        status: "success",
        output: `Database ${operation.toUpperCase()} successful: key='${key}', value='${val}'`,
      });
    }

    // If-Else Evaluator
    if (subType === "if-else") {
      const conditionValue = inputs.condition || config.condition || "true";
      const isTrue = conditionValue === "true" || conditionValue === true || conditionValue === "1" || String(conditionValue).toLowerCase() === "yes";
      return res.json({
        status: "success",
        output: isTrue ? "true" : "false",
      });
    }

    // Default fallback
    return res.json({
      status: "success",
      output: `Executed node ${subType} successfully with parameters.`,
    });

  } catch (error: any) {
    console.error("Error executing node on server:", error);
    return res.status(500).json({
      status: "error",
      message: error.message || "An unexpected error occurred during node execution.",
    });
  }
});

// 2. Chat / workflow suggestion endpoint
app.post("/api/ai-assistant", async (req, res) => {
  const { message, workflowContext } = req.body;

  try {
    const userPrompt = `You are a visual node-workflow orchestrator assistant for "CanvasFlow".
You can suggest adding specific nodes based on user needs.
Current workspace workflow has these nodes: ${JSON.stringify(workflowContext || [])}.

Answer the user's message concisely. 
If they want to create a workflow or a specific node, reply to them and optionally suggest a "node operation" in the response metadata.
Your suggestions should align with these node subTypes:
1. "chatgpt" (AI generator)
2. "translator" (AI translator)
3. "summarizer" (AI summarizer)
4. "kv-store" (Database store)
5. "api-request" (HTTP trigger)
6. "if-else" (Condition branching)
7. "user-input" (Text Input node)
8. "log-viewer" (Log Output node)

Provide your reply in JSON format with these exact properties:
- reply: (string, explanation in rich text or friendly markdown)
- suggestNodes: (optional array of new nodes to create, each having { name, type: "AI"|"Database"|"HTTP"|"Condition"|"Logic"|"End", subType, x, y, config: {} })

User message: "${message}"`;

    try {
      const ai = getAiClient();
      const response = await ai.models.generateContent({
        model: "gemini-3.5-flash",
        contents: userPrompt,
        config: {
          responseMimeType: "application/json",
        },
      });

      const result = JSON.parse(response.text || "{}");
      return res.json({
        reply: result.reply || "I'm ready to assist you in designing your workflows.",
        suggestNodes: result.suggestNodes || null,
      });

    } catch (err: any) {
      if (err.message === "API_KEY_MISSING") {
        // Fallback response for assistant if API key is not configured
        let reply = "I would love to help you build that! Since the Gemini API key is currently in fallback mode, I can mock suggestions for you.";
        let suggestNodes: any[] = [];

        const lower = message.toLowerCase();
        if (lower.includes("translate") || lower.includes("translation") || lower.includes("spanish") || lower.includes("french")) {
          reply = "I've designed a translation workflow for you! It takes user input, runs it through an AI translator, and prints it out.";
          suggestNodes = [
            {
              name: "User Input",
              type: "Logic",
              subType: "user-input",
              x: 100,
              y: 200,
              config: { value: "Hello, my friend!" }
            },
            {
              name: "AI Translator",
              type: "AI",
              subType: "translator",
              x: 400,
              y: 200,
              config: { targetLanguage: "Spanish" }
            },
            {
              name: "Execution Log",
              type: "End",
              subType: "log-viewer",
              x: 700,
              y: 200,
              config: {}
            }
          ];
        } else if (lower.includes("summar") || lower.includes("short")) {
          reply = "Here is an AI summarization pipeline. It fetches data from an API, summarizes the output, and writes the summary into a database.";
          suggestNodes = [
            {
              name: "Fetch Articles",
              type: "HTTP",
              subType: "api-request",
              x: 100,
              y: 150,
              config: { url: "https://api.example.com/news", method: "GET" }
            },
            {
              name: "AI Summarizer",
              type: "AI",
              subType: "summarizer",
              x: 400,
              y: 150,
              config: { wordLimit: 25 }
            },
            {
              name: "Backup Database",
              type: "Database",
              subType: "kv-store",
              x: 700,
              y: 150,
              config: { operation: "write", key: "summary_result" }
            }
          ];
        } else {
          reply = `Here is a custom AI node structure to help you get started with: "${message}". Click the add nodes button below!`;
          suggestNodes = [
            {
              name: "AI Chat Agent",
              type: "AI",
              subType: "chatgpt",
              x: 300,
              y: 200,
              config: { prompt: "Explain modern flow orchestration.", systemInstruction: "Be extremely concise." }
            }
          ];
        }

        return res.json({ reply, suggestNodes });
      }
      throw err;
    }

  } catch (error: any) {
    console.error("Error in AI assistant endpoint:", error);
    return res.status(500).json({
      reply: "Sorry, I had an error analyzing your request. Let's try again!",
      error: error.message,
    });
  }
});

// Setup Vite Dev Server / Static files
async function setupServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
    console.log("Vite development middleware mounted.");
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
    console.log("Serving static files from dist.");
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`CanvasFlow Server running on port ${PORT}`);
  });
}

setupServer();

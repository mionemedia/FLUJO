import logging, sys

# 1) Clear any default handlers
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)

# 2) Create a stderr-only handler
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.INFO)
stderr_handler.setFormatter(
    logging.Formatter("%(levelname)s:%(name)s:%(message)s")
)

# 3) Attach it to the root logger
logging.root.addHandler(stderr_handler)
logging.root.setLevel(logging.INFO)

# 4) Optionally suppress httpx/httpcore DEBUG noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Now import everything else
import json, asyncio, traceback
from typing import Dict, Any

# Force unbuffered Python output
import os
os.environ["PYTHONUNBUFFERED"] = "1"

# LangChain imports
from langchain_ollama import ChatOllama
from langchain.schema import HumanMessage, AIMessage, SystemMessage

# Ollama configuration
MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama2")
BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# JSON-RPC error codes
class JsonRpcError(Exception):
    """Base class for JSON-RPC errors."""
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)

# Get logger for this module
logger = logging.getLogger(__name__)

# Set Windows-specific event loop policy
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class McpServer:
    def __init__(self):
        # Initialize LangChain chat model
        try:
            # Test Ollama connection first
            import httpx
            with httpx.Client() as client:
                response = client.get(f"{BASE_URL}/api/version")
                if not response.is_success:
                    raise ConnectionError(f"Failed to connect to Ollama at {BASE_URL}: {response.text}")
                logger.info("Connected to Ollama %s", response.json().get("version", "unknown"))
            
            # Initialize ChatOllama with verified connection
            self.chat_model = ChatOllama(
                model=MODEL_NAME,
                base_url=BASE_URL,
                temperature=0.7,
                stop=["Human:", "Assistant:"]
            )
            logger.info("Initialized ChatOllama with model=%s at %s", MODEL_NAME, BASE_URL)
        except Exception as e:
            sys.stderr.write(f"Fatal error initializing ChatOllama: {str(e)}\n")
            traceback.print_exc(file=sys.stderr)
            raise
        
        # Initialize state and method registry
        self._shutdown_requested = False
        self._methods = {
            "list_tools":  self.list_tools,
            "invoke_tool": self.invoke_tool,
            "ping":        self.ping,
            "shutdown":    self.shutdown,
        }
    
    async def list_tools(self, **_):
        """List available tools and their descriptions."""
        return {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo back the input message",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "Message to echo back"}
                        },
                        "required": ["message"]
                    }
                },
                {
                    "name": "add",
                    "description": "Add two numbers",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "number", "description": "First number"},
                            "b": {"type": "number", "description": "Second number"}
                        },
                        "required": ["a", "b"]
                    }
                },
                {
                    "name": "chat",
                    "description": "Chat with LangChain model",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "messages": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "role": {"type": "string"},
                                        "content": {"type": "string"}
                                    }
                                }
                            }
                        },
                        "required": ["messages"]
                    }
                }
            ]
        }
    
    async def ping(self, **_):
        """Health check endpoint."""
        return "pong"
    
    async def shutdown(self, **_):
        """Request server shutdown."""
        self._shutdown_requested = True
        return "shutting down"
        
    async def send_handshake(self):
        """Send initial handshake response to indicate server is ready."""
        msg = {
            "jsonrpc": "2.0",
            "method": "mcp/server_ready",
            "id": 0,
            "params": {
                "name": "langchain-mcp",
                "version": "0.1.0",
                "protocols": ["mcp/1.0"],
                "capabilities": ["list_tools", "invoke_tool", "ping", "shutdown"]
            }
        }
        sys.stdout.buffer.write(json.dumps(msg).encode() + b"\n")
        sys.stdout.buffer.flush()

    async def run(self):
        """Run the MCP server using stdio transport."""
        await self.send_handshake()
        await self._read_loop()

    async def _read_loop(self):
        while True:
            raw = sys.stdin.buffer.readline()
            if not raw:
                await asyncio.sleep(0.1)
                continue

            req = json.loads(raw)
            mid    = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            handler = self._methods.get(method)
            if not handler:
                resp = {
                    "jsonrpc":"2.0",
                    "error": {"code": -32601, "message": f"Unknown method {method}"},
                    "id": mid
                }
            else:
                result = await handler(**params)
                resp = {"jsonrpc":"2.0","result":result,"id":mid}

            sys.stdout.buffer.write(json.dumps(resp).encode() + b"\n")
            sys.stdout.buffer.flush()

            if method == "shutdown":
                break
    
    async def invoke_tool(self, name: str, arguments: dict) -> Dict[str, Any]:
        """Invoke a tool by name with the given arguments."""
        if name == "echo":
            return {"echo": arguments.get("message", "")}
        elif name == "add":
            a = float(arguments.get("a", 0))
            b = float(arguments.get("b", 0))
            return {"sum": a + b}
        elif name == "chat":
            messages = arguments.get("messages", [])
            # Convert messages to LangChain format
            lc_messages = []
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                elif role == "user":
                    lc_messages.append(HumanMessage(content=content))
            # Call ChatOllama and return response
            response = await self.chat_model.agenerate([lc_messages])
            return {"response": response.generations[0][0].text}
        else:
            raise JsonRpcError(-32001, f"Unknown tool: {name}")

def is_pip_install():
    """Check if the script is being run as part of pip install."""
    import inspect
    for frame in inspect.stack():
        if frame.filename.endswith('pip') or 'pip' in frame.filename:
            return True
    return False

def handle_signal(signum, frame):
    """Handle shutdown signals."""
    logger.info("Received signal %d, initiating shutdown...", signum)
    sys.exit(0)

# Set up signal handlers
import signal
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)
if sys.platform != "win32":
    # SIGQUIT is not available on Windows
    signal.signal(signal.SIGQUIT, handle_signal)

if __name__ == "__main__":
    # Set up binary mode for stdin/stdout on Windows
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    # run the server
    asyncio.run(McpServer().run())

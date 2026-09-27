from shared.env import load_dotenv

load_dotenv()

from mcp_servers.curbside_mcp.server import main  # noqa: E402

main()

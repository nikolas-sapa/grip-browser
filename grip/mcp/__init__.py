"""Optional MCP surface for grip.

Deliberately empty: importing `grip.mcp.server` is what pulls in the `mcp`
package, which ships only under the `[mcp]` extra. Re-exporting it here would
make `import grip.mcp` fail on a base install.
"""

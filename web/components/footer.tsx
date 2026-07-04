export function Footer() {
  return (
    <footer className="border-t border-white/[0.06] px-6 py-8">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-white/25 font-mono">
        <span>grip · MIT License</span>
        <div className="flex gap-6">
          <a
            href="https://github.com/84yk8btb9f-prog/grip-browser"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-white/50 transition-colors"
          >
            GitHub
          </a>
          <a
            href="https://github.com/84yk8btb9f-prog/grip-browser#readme"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-white/50 transition-colors"
          >
            README
          </a>
          <a
            href="https://pypi.org/project/grip-browser"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-white/50 transition-colors"
          >
            PyPI
          </a>
        </div>
      </div>
    </footer>
  );
}

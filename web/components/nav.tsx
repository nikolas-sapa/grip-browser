"use client";

import { motion } from "framer-motion";

function GithubIcon({ size = 13 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844a9.59 9.59 0 012.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
    </svg>
  );
}

export function Nav() {
  return (
    <motion.header
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-4
                 border-b border-white/[0.06] bg-[#09090b]/80 backdrop-blur-md"
    >
      {/* Logo */}
      <a href="/" className="flex items-center gap-2">
        <span className="text-base font-semibold tracking-tight text-white">
          grip
        </span>
        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-white/50">
          v0.2
        </span>
      </a>

      {/* Right side */}
      <div className="flex items-center gap-3">
        <a
          href="https://github.com/nikolassapalidis/agentbrowser"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 rounded-full border border-white/10
                     bg-white/[0.04] px-3 py-1.5 text-xs text-white/70
                     hover:bg-white/[0.08] hover:text-white transition-colors duration-150"
        >
          <GithubIcon size={13} />
          <span>GitHub</span>
        </a>
        <a
          href="#install"
          className="rounded-full bg-white px-4 py-1.5 text-xs font-medium text-black
                     hover:bg-white/90 transition-colors duration-150"
        >
          pip install
        </a>
      </div>
    </motion.header>
  );
}

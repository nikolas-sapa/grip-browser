import { Nav } from "@/components/nav";
import { Hero } from "@/components/hero";
import { TokenCost } from "@/components/token-cost";
import { Mechanisms } from "@/components/mechanisms";
import { Delta } from "@/components/delta";
import { TaskSuccess } from "@/components/task-success";
import { CodeShowcase } from "@/components/code-showcase";
import { Cli } from "@/components/cli";
import { Features } from "@/components/features";
import { Hardening } from "@/components/hardening";
import { Mcp } from "@/components/mcp";
import { Limits } from "@/components/limits";
import { Install } from "@/components/install";
import { Footer } from "@/components/footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <TokenCost />
        <div className="mx-auto h-px max-w-6xl rule" />
        <Mechanisms />
        <Delta />
        <TaskSuccess />
        <CodeShowcase />
        <Cli />
        <Features />
        <Hardening />
        <Mcp />
        <Limits />
        <Install />
      </main>
      <Footer />
    </>
  );
}

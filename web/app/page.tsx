import { Nav } from "@/components/nav";
import { Hero } from "@/components/hero";
import { TokenCost } from "@/components/token-cost";
import { Mechanisms } from "@/components/mechanisms";
import { Delta } from "@/components/delta";
import { CodeShowcase } from "@/components/code-showcase";
import { Features } from "@/components/features";
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
        <CodeShowcase />
        <Features />
        <Limits />
        <Install />
      </main>
      <Footer />
    </>
  );
}

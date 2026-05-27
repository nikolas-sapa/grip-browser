import { Nav } from "@/components/nav";
import { Hero } from "@/components/hero";
import { Features } from "@/components/features";
import { CodeShowcase } from "@/components/code-showcase";
import { Comparison } from "@/components/comparison";
import { Install } from "@/components/install";
import { Footer } from "@/components/footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <Features />
        <CodeShowcase />
        <Comparison />
        <Install />
      </main>
      <Footer />
    </>
  );
}

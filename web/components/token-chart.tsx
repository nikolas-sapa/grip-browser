"use client";

import { useTheme } from "next-themes";
import { AreaChart } from "@/components/dither-kit/area-chart";
import { Area } from "@/components/dither-kit/area";
import { Grid } from "@/components/dither-kit/grid";
import { Legend } from "@/components/dither-kit/legend";
import { Tooltip } from "@/components/dither-kit/tooltip";
import { XAxis } from "@/components/dither-kit/x-axis";
import { YAxis } from "@/components/dither-kit/y-axis";
import type { ChartConfig } from "@/components/dither-kit/chart-context";
import { scenarios } from "@/lib/metrics";

const config: ChartConfig = {
  rawHtml: { label: "Raw HTML every turn", color: "grey" },
  grip: { label: "grip", color: "blue" },
};

const compact = (n: number) =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000
      ? `${Math.round(n / 1_000)}k`
      : String(n);

export function TokenChart() {
  const { resolvedTheme } = useTheme();

  return (
    <div
      // The canvas repaints on resize and data change, not on a class mutation,
      // so remount it when the theme flips or the dither stays tuned for the
      // previous background.
      key={resolvedTheme}
      // The chart root is h-full; without a measured height here it paints
      // nothing and the build still passes.
      className="h-[280px] w-full sm:h-[380px]"
    >
      <AreaChart
        data={scenarios}
        config={config}
        // 36px of gutter clips a seven-character mono tick.
        margins={{ left: 56, top: 28, right: 16, bottom: 28 }}
        animationDuration={1100}
      >
        <Grid />
        <XAxis dataKey="label" />
        <YAxis tickFormatter={compact} />
        <Area dataKey="rawHtml" />
        <Area dataKey="grip" />
        <Legend />
        <Tooltip
          labelKey="label"
          valueFormatter={(value) => `${value.toLocaleString()} tok`}
        />
      </AreaChart>
    </div>
  );
}

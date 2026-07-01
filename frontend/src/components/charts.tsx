import type { EChartsOption } from "echarts";
import type { AnalysisReport, CountItem, PainPoint } from "../lib/api";
import { Chart } from "./Chart";

const textColor = "#6b7280";
const gridColor = "#e5e7eb";
const orange = "#f97316";
const blue = "#3b82f6";
const green = "#16a34a";
const rose = "#be123c";
const amber = "#f59e0b";

export function TrendChart({ trend }: { trend: AnalysisReport["trend"] }) {
  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid: { left: 34, right: 18, top: 24, bottom: 32 },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: trend.map((item) => item.month),
      axisLabel: { color: textColor },
      axisLine: { lineStyle: { color: gridColor } },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      splitLine: { lineStyle: { color: gridColor } },
      axisLabel: { color: textColor },
    },
    series: [
      {
        type: "line",
        data: trend.map((item) => item.count),
        smooth: true,
        symbolSize: 7,
        lineStyle: { color: blue, width: 3 },
        itemStyle: { color: blue },
        areaStyle: { color: "rgba(37,99,235,0.12)" },
      },
    ],
  };
  return <Chart option={option} height={250} />;
}

type SentimentLabels = {
  positive: string;
  neutral: string;
  negative: string;
};

const defaultSentimentLabels: SentimentLabels = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
};

export function SentimentChart({
  sentiment,
  labels = defaultSentimentLabels,
}: {
  sentiment: AnalysisReport["sentiment"];
  labels?: SentimentLabels;
}) {
  const option: EChartsOption = {
    tooltip: { trigger: "item" },
    legend: { bottom: 0, textStyle: { color: textColor } },
    series: [
      {
        type: "pie",
        radius: ["46%", "70%"],
        center: ["50%", "45%"],
        avoidLabelOverlap: true,
        label: { formatter: "{b}\n{d}%" },
        color: [green, "#94a3b8", rose],
        data: [
          { name: labels.positive, value: sentiment.positive },
          { name: labels.neutral, value: sentiment.neutral },
          { name: labels.negative, value: sentiment.negative },
        ],
      },
    ],
  };
  return <Chart option={option} height={250} />;
}

export function TopicBarChart({ points }: { points: PainPoint[] }) {
  const sorted = [...points].slice(0, 7).reverse();
  const option: EChartsOption = {
    grid: { left: 128, right: 20, top: 18, bottom: 24 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "value",
      minInterval: 1,
      splitLine: { lineStyle: { color: gridColor } },
      axisLabel: { color: textColor },
    },
    yAxis: {
      type: "category",
      data: sorted.map((item) => item.topic),
      axisLabel: { color: textColor },
      axisLine: { lineStyle: { color: gridColor } },
    },
    series: [
      {
        type: "bar",
        data: sorted.map((item) => item.count),
        itemStyle: { color: orange, borderRadius: [0, 6, 6, 0] },
      },
    ],
  };
  return <Chart option={option} height={300} />;
}

export function CoverageChart({ subreddits }: { subreddits: CountItem[] }) {
  const items = subreddits.slice(0, 8);
  const option: EChartsOption = {
    grid: { left: 42, right: 18, top: 20, bottom: 54 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "category",
      data: items.map((item) => `r/${item.name}`),
      axisLabel: { color: textColor, rotate: 28 },
      axisLine: { lineStyle: { color: gridColor } },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      splitLine: { lineStyle: { color: gridColor } },
      axisLabel: { color: textColor },
    },
    series: [
      {
        type: "bar",
        data: items.map((item) => item.count),
        itemStyle: { color: amber, borderRadius: [6, 6, 0, 0] },
      },
    ],
  };
  return <Chart option={option} height={270} />;
}

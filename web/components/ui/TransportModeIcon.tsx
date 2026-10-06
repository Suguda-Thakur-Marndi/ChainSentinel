import React from "react";
import {
  Ship,
  Plane,
  Truck,
  TrainFront,
  Warehouse,
  Anchor,
  Container,
  Package,
  LucideIcon,
} from "lucide-react";

export type TransportMode =
  | "ocean"
  | "air"
  | "road"
  | "rail"
  | "warehouse"
  | "port"
  | "airport"
  | "container"
  | "unknown";

/**
 * Normalizes any backend, database, API, or legacy transportation string into
 * a canonical TransportMode enum.
 *
 * Handles casing, whitespace, hyphens, and multi-word phrases such as:
 * - "Ocean Freight", "MARITIME", "sea", "vessel" -> "ocean"
 * - "Air Freight", "FLIGHT", "aviation", "airplane" -> "air"
 * - "Road Logistics", "TRUCK", "highway", "trucking" -> "road"
 * - "Intermodal Rail", "TRAIN", "railway", "rail_freight" -> "rail"
 * - "distribution center", "fulfillment center", "warehouse" -> "warehouse"
 * - "seaport", "marine terminal", "port" -> "port"
 * - "airport", "air terminal" -> "airport"
 */
export function normalizeTransportMode(mode?: string | null): TransportMode {
  if (!mode || typeof mode !== "string") {
    return "unknown";
  }

  const clean = mode.trim().toLowerCase().replace(/[-_]/g, " ");
  const words = clean.split(/\s+/);

  // Ocean / Maritime
  if (
    clean === "ocean" ||
    clean === "sea" ||
    clean === "maritime" ||
    clean === "vessel" ||
    clean === "ship" ||
    words.includes("ocean") ||
    words.includes("maritime") ||
    words.includes("vessel") ||
    words.includes("ship") ||
    words.includes("ships") ||
    words.includes("boat") ||
    clean.includes("ocean freight") ||
    clean.includes("container ship") ||
    clean.includes("bulk carrier") ||
    clean.includes("cargo ship") ||
    clean.includes("water")
  ) {
    return "ocean";
  }

  // Airport (check before air to match air terminals/airports specifically)
  if (
    clean === "airport" ||
    words.includes("airport") ||
    clean.includes("air terminal") ||
    clean.includes("airfield")
  ) {
    return "airport";
  }

  // Air / Aviation
  if (
    clean === "air" ||
    clean === "flight" ||
    clean === "aviation" ||
    clean === "airplane" ||
    clean === "aircraft" ||
    clean === "plane" ||
    words.includes("air") ||
    words.includes("flight") ||
    words.includes("aviation") ||
    words.includes("airplane") ||
    words.includes("aircraft") ||
    words.includes("plane") ||
    clean.includes("air freight") ||
    clean.includes("air cargo") ||
    clean.includes("airfreight")
  ) {
    return "air";
  }

  // Road / Trucking
  if (
    clean === "road" ||
    clean === "truck" ||
    clean === "trucking" ||
    clean === "highway" ||
    clean === "ground" ||
    clean === "van" ||
    words.includes("road") ||
    words.includes("truck") ||
    words.includes("trucks") ||
    words.includes("trucking") ||
    words.includes("highway") ||
    clean.includes("road freight") ||
    clean.includes("road logistics") ||
    clean.includes("motor freight")
  ) {
    return "road";
  }

  // Rail / Railway
  if (
    clean === "rail" ||
    clean === "railway" ||
    clean === "train" ||
    words.includes("rail") ||
    words.includes("railway") ||
    words.includes("train") ||
    words.includes("trains") ||
    clean.includes("rail freight") ||
    clean.includes("intermodal rail") ||
    clean.includes("railcar") ||
    clean.includes("freight train")
  ) {
    return "rail";
  }

  // Warehouse / Distribution Center
  if (
    clean === "warehouse" ||
    clean === "storage" ||
    clean === "dc" ||
    words.includes("warehouse") ||
    words.includes("warehouses") ||
    words.includes("storage") ||
    clean.includes("distribution center") ||
    clean.includes("fulfillment center") ||
    clean.includes("storage facility")
  ) {
    return "warehouse";
  }


  // Port / Seaport / Terminal
  if (
    clean === "port" ||
    clean === "seaport" ||
    clean === "harbor" ||
    clean === "harbour" ||
    words.includes("port") ||
    words.includes("ports") ||
    words.includes("seaport") ||
    words.includes("harbor") ||
    words.includes("terminal") ||
    clean.includes("marine terminal") ||
    clean.includes("port terminal")
  ) {
    return "port";
  }

  // Container / Intermodal cargo
  if (
    clean === "container" ||
    clean === "cargo" ||
    clean === "freight" ||
    words.includes("container") ||
    words.includes("containers") ||
    words.includes("cargo") ||
    clean.includes("intermodal container") ||
    clean.includes("shipping container")
  ) {
    return "container";
  }

  return "unknown";
}

/**
 * Returns user-facing, high-precision label for a transport mode.
 */
export function getTransportModeLabel(mode?: string | null): string {
  const norm = normalizeTransportMode(mode);
  switch (norm) {
    case "ocean":
      return "Ocean Freight";
    case "air":
      return "Air Freight";
    case "road":
      return "Road Freight";
    case "rail":
      return "Rail Freight";
    case "warehouse":
      return "Warehouse / DC";
    case "port":
      return "Port / Seaport";
    case "airport":
      return "Airport Terminal";
    case "container":
      return "Container Cargo";
    default:
      return mode && mode.trim().length > 0 ? mode.trim() : "Multimodal Cargo";
  }
}

/**
 * Returns concise single-word label suitable for small chips or tables.
 */
export function getTransportModeShortLabel(mode?: string | null): string {
  const norm = normalizeTransportMode(mode);
  switch (norm) {
    case "ocean":
      return "Ocean";
    case "air":
      return "Air";
    case "road":
      return "Road";
    case "rail":
      return "Rail";
    case "warehouse":
      return "Warehouse";
    case "port":
      return "Port";
    case "airport":
      return "Airport";
    case "container":
      return "Container";
    default:
      return "Cargo";
  }
}

/**
 * Returns the appropriate Lucide icon component for the normalized mode.
 */
export function getTransportModeIconComponent(mode?: string | null): LucideIcon {
  const norm = normalizeTransportMode(mode);
  switch (norm) {
    case "ocean":
      return Ship;
    case "air":
    case "airport":
      return Plane;
    case "road":
      return Truck;
    case "rail":
      return TrainFront;
    case "warehouse":
      return Warehouse;
    case "port":
      return Anchor;
    case "container":
      return Container;
    default:
      return Package;
  }
}

/**
 * Semantic tokens adhering to RiskWise's defense-grade palette.
 */
export function getTransportModeTokens(mode?: string | null) {
  const norm = normalizeTransportMode(mode);
  switch (norm) {
    case "ocean":
      return {
        text: "text-sky-400",
        bg: "bg-sky-950/40",
        border: "border-sky-800/60",
        hex: "#38BDF8",
      };
    case "air":
    case "airport":
      return {
        text: "text-amber-400",
        bg: "bg-amber-950/40",
        border: "border-amber-800/60",
        hex: "#F59E0B",
      };
    case "road":
      return {
        text: "text-emerald-400",
        bg: "bg-emerald-950/40",
        border: "border-emerald-800/60",
        hex: "#10B981",
      };
    case "rail":
      return {
        text: "text-purple-400",
        bg: "bg-purple-950/40",
        border: "border-purple-800/60",
        hex: "#A855F7",
      };
    case "warehouse":
      return {
        text: "text-orange-400",
        bg: "bg-orange-950/40",
        border: "border-orange-800/60",
        hex: "#F97316",
      };
    case "port":
      return {
        text: "text-teal-400",
        bg: "bg-teal-950/40",
        border: "border-teal-800/60",
        hex: "#14B8A6",
      };
    case "container":
      return {
        text: "text-blue-400",
        bg: "bg-blue-950/40",
        border: "border-blue-800/60",
        hex: "#60A5FA",
      };
    default:
      return {
        text: "text-slate-400",
        bg: "bg-slate-800/60",
        border: "border-slate-700/60",
        hex: "#94A3B8",
      };
  }
}

export interface TransportModeIconProps extends Omit<React.SVGProps<SVGSVGElement>, "mode"> {
  mode?: string | null;
  size?: number | "sm" | "md" | "lg" | "xl";
  className?: string;
  variant?: "plain" | "semantic";
  title?: string;
  strokeWidth?: number;
}

/**
 * Reusable, centralized transport mode vector icon component.
 * Normalizes any backend string and renders the exact Lucide vector icon.
 */
export function TransportModeIcon({
  mode,
  size = "md",
  className = "",
  variant = "plain",
  title,
  strokeWidth = 2,
  ...rest
}: TransportModeIconProps) {
  const norm = normalizeTransportMode(mode);
  const label = title || getTransportModeLabel(mode);
  const tokens = getTransportModeTokens(mode);

  let pixelSize = 18;
  if (typeof size === "number") {
    pixelSize = size;
  } else {
    switch (size) {
      case "sm":
        pixelSize = 16;
        break;
      case "md":
        pixelSize = 18;
        break;
      case "lg":
        pixelSize = 22;
        break;
      case "xl":
        pixelSize = 26;
        break;
    }
  }

  const colorClass = variant === "semantic" ? tokens.text : "";
  const commonProps = {
    width: pixelSize,
    height: pixelSize,
    strokeWidth,
    className: `inline-block flex-shrink-0 align-middle ${colorClass} ${className}`.trim(),
    role: "img",
    "aria-label": label,
    ...rest,
  };

  switch (norm) {
    case "ocean":
      return <Ship {...commonProps} />;
    case "air":
    case "airport":
      return <Plane {...commonProps} />;
    case "road":
      return <Truck {...commonProps} />;
    case "rail":
      return <TrainFront {...commonProps} />;
    case "warehouse":
      return <Warehouse {...commonProps} />;
    case "port":
      return <Anchor {...commonProps} />;
    case "container":
      return <Container {...commonProps} />;
    default:
      return <Package {...commonProps} />;
  }
}

export interface TransportModeBadgeProps {
  mode?: string | null;
  variant?: "semantic" | "neutral" | "subtle";
  size?: "xs" | "sm" | "md";
  showLabel?: boolean;
  shortLabel?: boolean;
  className?: string;
  title?: string;
}

/**
 * High-density accessible badge displaying the transport vector icon + label.
 */
export function TransportModeBadge({
  mode,
  variant = "semantic",
  size = "sm",
  showLabel = true,
  shortLabel = false,
  className = "",
  title,
}: TransportModeBadgeProps) {
  const label = shortLabel ? getTransportModeShortLabel(mode) : getTransportModeLabel(mode);
  const tooltip = title || getTransportModeLabel(mode);
  const tokens = getTransportModeTokens(mode);

  const iconSize = size === "xs" ? 12 : size === "md" ? 16 : 14;

  let basePadding = "px-2 py-0.5 text-[11px]";
  if (size === "xs") {
    basePadding = "px-1.5 py-0.5 text-[10px]";
  } else if (size === "md") {
    basePadding = "px-2.5 py-1 text-xs";
  }

  let colorStyle = "";
  if (variant === "semantic") {
    colorStyle = `${tokens.bg} ${tokens.border} ${tokens.text} border`;
  } else if (variant === "subtle") {
    colorStyle = "bg-slate-800/80 text-slate-300 border border-slate-700/80";
  } else {
    colorStyle = "bg-surface text-foreground border border-arch";
  }

  return (
    <span
      title={tooltip}
      className={`inline-flex items-center gap-1.5 rounded font-mono font-medium tracking-tight whitespace-nowrap select-none ${basePadding} ${colorStyle} ${className}`.trim()}
    >
      <TransportModeIcon
        mode={mode}
        size={iconSize}
        variant={variant === "semantic" ? "semantic" : "plain"}
        aria-hidden="true"
      />
      {showLabel && <span>{label}</span>}
    </span>
  );
}

/**
 * Filter configuration items with mode icon mapping for dropdowns and filter toolbars.
 */
export const TRANSPORT_FILTER_OPTIONS: { value: string; label: string; mode: TransportMode }[] = [
  { value: "ALL", label: "All Transport Modes", mode: "unknown" },
  { value: "OCEAN", label: "Ocean Freight", mode: "ocean" },
  { value: "AIR", label: "Air Freight", mode: "air" },
  { value: "ROAD", label: "Road Freight", mode: "road" },
  { value: "RAIL", label: "Rail Freight", mode: "rail" },
];

import { ThemeColors, ThemeName, ThemeMode } from "./types";

export const themePalettes: Record<ThemeName, { light: ThemeColors; dark: ThemeColors }> = {
  Ocean: {
    light: {
      primary: "#4F8CFF",
      success: "#34C759",
      warning: "#FFB340",
      danger: "#FF5E57",
      background: "#F5F7FB",
      surface: "rgba(255, 255, 255, 0.55)",
      border: "rgba(255, 255, 255, 0.35)",
      text: "#202530",
      secondaryText: "#667085",
    },
    dark: {
      primary: "#5E99FF",
      success: "#30D158",
      warning: "#FF9F0A",
      danger: "#FF453A",
      background: "#0F111A",
      surface: "rgba(20, 24, 38, 0.45)",
      border: "rgba(255, 255, 255, 0.08)",
      text: "#F5F7FB",
      secondaryText: "#94A3B8",
    },
  },
  Mint: {
    light: {
      primary: "#00C781",
      success: "#34C759",
      warning: "#FFB340",
      danger: "#FF5E57",
      background: "#F2FAF5",
      surface: "rgba(255, 255, 255, 0.55)",
      border: "rgba(255, 255, 255, 0.35)",
      text: "#152E20",
      secondaryText: "#5E7566",
    },
    dark: {
      primary: "#34D399",
      success: "#30D158",
      warning: "#FF9F0A",
      danger: "#FF453A",
      background: "#081C15",
      surface: "rgba(12, 36, 28, 0.45)",
      border: "rgba(255, 255, 255, 0.08)",
      text: "#E8F5E9",
      secondaryText: "#8FA396",
    },
  },
  Purple: {
    light: {
      primary: "#92400E", // Warm amber tone accent
      success: "#34C759",
      warning: "#FFB340",
      danger: "#FF5E57",
      background: "#FAF5FF",
      surface: "rgba(255, 255, 255, 0.55)",
      border: "rgba(255, 255, 255, 0.35)",
      text: "#2E1A47",
      secondaryText: "#7C6A94",
    },
    dark: {
      primary: "#C084FC",
      success: "#30D158",
      warning: "#FF9F0A",
      danger: "#FF453A",
      background: "#120B1E",
      surface: "rgba(28, 17, 44, 0.45)",
      border: "rgba(255, 255, 255, 0.08)",
      text: "#F5F3FF",
      secondaryText: "#A78BFA",
    },
  },
  Rose: {
    light: {
      primary: "#FF2D55",
      success: "#34C759",
      warning: "#FFB340",
      danger: "#FF5E57",
      background: "#FFF5F7",
      surface: "rgba(255, 255, 255, 0.55)",
      border: "rgba(255, 255, 255, 0.35)",
      text: "#400F1A",
      secondaryText: "#8C646D",
    },
    dark: {
      primary: "#FF375F",
      success: "#30D158",
      warning: "#FF9F0A",
      danger: "#FF453A",
      background: "#1C0D12",
      surface: "rgba(40, 18, 25, 0.45)",
      border: "rgba(255, 255, 255, 0.08)",
      text: "#FFF0F3",
      secondaryText: "#FDA4AF",
    },
  },
  Orange: {
    light: {
      primary: "#FF9500",
      success: "#34C759",
      warning: "#FFB340",
      danger: "#FF5E57",
      background: "#FFFBF5",
      surface: "rgba(255, 255, 255, 0.55)",
      border: "rgba(255, 255, 255, 0.35)",
      text: "#331E00",
      secondaryText: "#806640",
    },
    dark: {
      primary: "#FF9F0A",
      success: "#30D158",
      warning: "#FF9F0A",
      danger: "#FF453A",
      background: "#1E1202",
      surface: "rgba(42, 26, 6, 0.45)",
      border: "rgba(255, 255, 255, 0.08)",
      text: "#FFF3E0",
      secondaryText: "#FFB74D",
    },
  },
};

export function getThemeColors(name: ThemeName, mode: ThemeMode): ThemeColors {
  // Graceful Purple adaptation for the custom Light accent
  const palette = themePalettes[name] || themePalettes.Ocean;
  const colors = palette[mode];
  if (name === "Purple" && mode === "light") {
    return {
      ...colors,
      primary: "#AF52DE", // Set Purple light accent primary correctly
    };
  }
  return colors;
}

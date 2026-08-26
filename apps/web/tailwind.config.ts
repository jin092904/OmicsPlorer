import type { Config } from "tailwindcss";

// 디자인 v2 — 한국어 가독성 + 차분한 학술 톤. 다크모드는 `class` 기반 (.dark on <html>).
//
// 모든 색은 globals.css 의 CSS 변수를 참조한다 (`rgb(var(--token) / <alpha-value>)`).
// 라이트/다크 토큰 매핑은 globals.css 의 `:root` 와 `.dark` 에서 정의.
const tone = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: tone("background"),
        "on-background": tone("on-background"),
        surface: tone("surface"),
        "on-surface": tone("on-surface"),
        "on-surface-variant": tone("on-surface-variant"),
        "surface-container-lowest": tone("surface-container-lowest"),
        "surface-container-low": tone("surface-container-low"),
        "surface-container": tone("surface-container"),
        "surface-container-high": tone("surface-container-high"),
        "surface-container-highest": tone("surface-container-highest"),
        "surface-variant": tone("surface-variant"),
        outline: tone("outline"),
        "outline-variant": tone("outline-variant"),
        primary: tone("primary"),
        "on-primary": tone("on-primary"),
        "primary-container": tone("primary-container"),
        "on-primary-container": tone("on-primary-container"),
        secondary: tone("secondary"),
        "on-secondary": tone("on-secondary"),
        "secondary-container": tone("secondary-container"),
        "on-secondary-container": tone("on-secondary-container"),
        tertiary: tone("tertiary"),
        "on-tertiary": tone("on-tertiary"),
        "tertiary-container": tone("tertiary-container"),
        "on-tertiary-container": tone("on-tertiary-container"),
        error: tone("error"),
        "on-error": tone("on-error"),
        "error-container": tone("error-container"),
        "on-error-container": tone("on-error-container"),
      },
      fontFamily: {
        sans: [
          "Pretendard Variable",
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "Apple SD Gothic Neo",
          "Noto Sans KR",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        // 약간 더 큰 line-height 로 한글 가독성 ↑
        "headline-lg": ["32px", { lineHeight: "44px", letterSpacing: "-0.02em", fontWeight: "700" }],
        "headline-md": ["22px", { lineHeight: "32px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "headline-sm": ["17px", { lineHeight: "26px", fontWeight: "600" }],
        "body-lg": ["16px", { lineHeight: "26px", fontWeight: "400" }],
        "body-md": ["14px", { lineHeight: "22px", fontWeight: "400" }],
        "body-sm": ["13px", { lineHeight: "20px", fontWeight: "400" }],
        "label-caps": ["11px", { lineHeight: "16px", letterSpacing: "0.06em", fontWeight: "600" }],
        "mono-data": ["13px", { lineHeight: "20px", fontWeight: "400" }],
      },
      borderRadius: {
        sm: "0.25rem",
        DEFAULT: "0.375rem",
        md: "0.5rem",
        lg: "0.625rem",
        xl: "0.875rem",
      },
      maxWidth: {
        "container-max": "1200px",
      },
      spacing: {
        gutter: "20px",
        lg: "24px",
        md: "16px",
        sm: "8px",
        xl: "32px",
        xs: "4px",
        base: "4px",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04)",
        "card-hover": "0 4px 12px -2px rgb(0 0 0 / 0.06), 0 2px 4px -2px rgb(0 0 0 / 0.04)",
      },
    },
  },
  plugins: [],
};

export default config;

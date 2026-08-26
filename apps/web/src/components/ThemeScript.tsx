// FOUC 방지 — body 렌더 전에 .dark 클래스를 적용한다.
// dangerouslySetInnerHTML 로 inline 스크립트 1회 실행. 쿠키 ↔ matchMedia 결합.
import { THEME_COOKIE } from "@/lib/theme";

export function ThemeScript() {
  const code = `
(function () {
  try {
    var m = document.cookie.match(/(?:^|; )${THEME_COOKIE}=([^;]+)/);
    var t = m ? decodeURIComponent(m[1]) : 'system';
    var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    var dark = t === 'dark' || (t !== 'light' && prefersDark);
    var root = document.documentElement;
    if (dark) root.classList.add('dark'); else root.classList.remove('dark');
  } catch (e) {}
})();
`;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}

// Types for scripts/check_js.py. The UI finds its own elements with querySelector and
// knows what they are (inputs, buttons); TypeScript only knows "Element". These
// overloads say so once, so the check reports real mistakes (unknown names, wrong
// calls) instead of asking for a cast on every line.
interface ParentNode {
  querySelector(selectors: string): any;
  querySelectorAll(selectors: string): NodeListOf<HTMLInputElement>;
}
interface Element { closest(selectors: string): any; }
interface EventTarget { closest(selectors: string): any; }

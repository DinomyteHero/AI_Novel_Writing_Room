import { Link, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

const navItems = [
  { path: "/", label: "Dashboard" },
  { path: "/pipeline", label: "Pipeline" },
  { path: "/quality", label: "Quality" },
  { path: "/story", label: "Story State" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <nav className="w-56 bg-gray-900 text-gray-100 flex flex-col">
        <div className="p-4 border-b border-gray-700">
          <h1 className="text-lg font-bold">AI Writers' Room</h1>
          <p className="text-xs text-gray-400 mt-1">Pipeline Dashboard</p>
        </div>
        <ul className="flex-1 py-2">
          {navItems.map((item) => (
            <li key={item.path}>
              <Link
                to={item.path}
                className={`block px-4 py-2 text-sm hover:bg-gray-800 ${
                  location.pathname === item.path
                    ? "bg-gray-800 text-white font-medium"
                    : "text-gray-300"
                }`}
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
        <div className="p-4 border-t border-gray-700 text-xs text-gray-500">
          Phase 5 v0.5.0
        </div>
      </nav>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div
          role="alert"
          className="bg-amber-100 border-b border-amber-300 text-amber-900 text-xs px-4 py-2"
        >
          <span className="font-semibold">Preview mode.</span>{" "}
          Web runs are not run-isolated — consecutive runs can overwrite chapter
          output. Use the CLI (<code className="font-mono">python src/main.py</code>)
          for production runs until run isolation is wired in a later phase.
        </div>
        <main className="flex-1 p-6 overflow-auto">{children}</main>
      </div>
    </div>
  );
}

import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import ChapterViewer from "./pages/ChapterViewer";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chapters/:chapter/:scene" element={<ChapterViewer />} />
      </Routes>
    </Layout>
  );
}

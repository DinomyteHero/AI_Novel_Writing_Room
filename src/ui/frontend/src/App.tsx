import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Pipeline from "./pages/Pipeline";
import ChapterViewer from "./pages/ChapterViewer";
import Quality from "./pages/Quality";
import StoryState from "./pages/StoryState";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/chapters/:chapter/:scene" element={<ChapterViewer />} />
        <Route path="/quality" element={<Quality />} />
        <Route path="/story" element={<StoryState />} />
      </Routes>
    </Layout>
  );
}

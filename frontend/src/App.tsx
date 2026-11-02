import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/Layout'
import { useApp } from './context'
import Admin from './pages/Admin'
import Assistant from './pages/Assistant'
import Departments from './pages/Departments'
import Defense from './pages/Defense'
import Feed from './pages/Feed'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Home from './pages/Home'
import Problems from './pages/Problems'
import Quality from './pages/Quality'
import Sources from './pages/Sources'

export default function App() {
  const { user, can } = useApp()
  if (!user) return <Login />
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/analytics" element={<Overview />} />
        <Route path="/problems" element={<Problems />} />
        <Route path="/departments" element={<Departments />} />
        <Route path="/defense" element={<Defense />} />
        <Route path="/feed" element={<Feed mode="all" />} />
        <Route path="/review" element={can('operator') ? <Feed mode="review" /> : <Navigate to="/feed" />} />
        <Route path="/geo" element={can('operator') ? <Feed mode="geo" /> : <Navigate to="/feed" />} />
        <Route path="/direct" element={can('operator') ? <Feed mode="direct" /> : <Navigate to="/feed" />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/sources" element={<Sources />} />
        <Route path="/quality" element={<Quality />} />
        <Route path="/admin" element={can('admin') ? <Admin /> : <Navigate to="/" />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </AppLayout>
  )
}

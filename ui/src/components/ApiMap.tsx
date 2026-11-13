import { useMemo, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { Html, Line, OrbitControls } from '@react-three/drei'
import type { ApiGraph, ApiNode } from '../lib/api'

type Point3 = [number, number, number]

const NODE_COLORS: Record<string, string> = {
  active: '#39e3d0',
  zombie: '#f5b84b',
  shadow: '#b28cff',
}

function pointFor(index: number, count: number): Point3 {
  if (count <= 1) return [0, 0, 0]
  const y = 1 - (index / (count - 1)) * 2
  const radius = Math.sqrt(1 - y * y)
  const angle = Math.PI * (3 - Math.sqrt(5)) * index
  const spread = 3.2
  return [
    Math.cos(angle) * radius * spread,
    y * spread,
    Math.sin(angle) * radius * spread,
  ]
}

function EndpointNode({
  endpoint,
  position,
  onSelect,
}: {
  endpoint: ApiNode
  position: Point3
  onSelect: (node: ApiNode) => void
}) {
  const [hovered, setHovered] = useState(false)
  const color = NODE_COLORS[endpoint.status] ?? '#94a3b8'
  return (
    <group position={position}>
      <mesh
        onClick={(event) => {
          event.stopPropagation()
          onSelect(endpoint)
        }}
        onPointerOver={(event) => {
          event.stopPropagation()
          setHovered(true)
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          setHovered(false)
          document.body.style.cursor = 'default'
        }}
      >
        <sphereGeometry args={[hovered ? 0.18 : 0.12, 14, 14]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={hovered ? 2.8 : 1.8}
          roughness={0.35}
        />
      </mesh>
      <mesh scale={hovered ? 2.3 : 1.8}>
        <sphereGeometry args={[0.12, 12, 12]} />
        <meshBasicMaterial color={color} transparent opacity={0.09} />
      </mesh>
      {hovered && (
        <Html distanceFactor={9} position={[0, 0.26, 0]} center>
          <div className="map-tooltip">
            <span className="text-teal-200">{endpoint.method}</span>{' '}
            {endpoint.path}
            <span className="ml-2 uppercase text-slate-500">{endpoint.status}</span>
          </div>
        </Html>
      )}
    </group>
  )
}

function ApiMap({
  graph,
  onSelect,
}: {
  graph: ApiGraph
  onSelect: (node: ApiNode) => void
}) {
  const nodes = useMemo(() => graph.nodes.slice(0, 100), [graph.nodes])
  const positions = useMemo(() => {
    return new Map(
      nodes.map((node, index) => [node.id, pointFor(index, nodes.length)]),
    )
  }, [nodes])
  const edges = useMemo(
    () =>
      graph.edges
        .slice(0, 200)
        .map((edge) => ({
          ...edge,
          start: positions.get(edge.source),
          end: positions.get(edge.target),
        }))
        .filter(
          (edge): edge is typeof edge & { start: Point3; end: Point3 } =>
            edge.start !== undefined && edge.end !== undefined,
        ),
    [graph.edges, positions],
  )

  return (
    <Canvas
      camera={{ position: [0, 0, 9], fov: 48 }}
      dpr={[1, 1.5]}
      gl={{ antialias: false, powerPreference: 'high-performance' }}
      onPointerMissed={() => document.body.style.setProperty('cursor', 'default')}
      performance={{ min: 0.65 }}
    >
      <color attach="background" args={['#080e16']} />
      <ambientLight intensity={0.7} />
      <pointLight position={[5, 4, 5]} intensity={0.8} color="#6ee7d8" />
      <group>
        {edges.map((edge, index) => (
          <Line
            key={`${edge.source}-${edge.target}-${index}`}
            points={[edge.start, edge.end]}
            color="#477d83"
            lineWidth={0.8}
            transparent
            opacity={0.32}
          />
        ))}
        {nodes.map((node, index) => (
          <EndpointNode
            endpoint={node}
            key={node.id}
            onSelect={onSelect}
            position={pointFor(index, nodes.length)}
          />
        ))}
      </group>
      <OrbitControls
        autoRotate
        autoRotateSpeed={0.18}
        dampingFactor={0.08}
        enableDamping
        enablePan={false}
        maxDistance={13}
        minDistance={5}
      />
    </Canvas>
  )
}

export default ApiMap

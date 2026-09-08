import concurrent.futures
import logging
import time
import uuid
from typing import List, Dict, Any, Callable
from observability.logger import app_logger
from observability.tracker import AgentTracker

logger = logging.getLogger(__name__)

class Orchestrator:
    """
    Lightweight graph runner supporting parallel fan-out, dependency management,
    topological execution, and node-level error propagation.
    """
    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        self.nodes: Dict[str, Callable] = {}
        self.edges: Dict[str, List[str]] = {}
        self.in_edges: Dict[str, set] = {}

    def add_node(self, name: str, func: Callable):
        """
        Registers an execution node in the workflow graph.
        """
        self.nodes[name] = func
        if name not in self.edges:
            self.edges[name] = []
        if name not in self.in_edges:
            self.in_edges[name] = set()

    def add_edge(self, from_node: str, to_nodes: Any):
        """
        Registers directed dependencies between nodes.
        to_nodes can be a string or a list of strings.
        """
        if isinstance(to_nodes, str):
            to_nodes = [to_nodes]

        if from_node not in self.edges:
            self.edges[from_node] = []
        if from_node not in self.in_edges:
            self.in_edges[from_node] = set()

        for target in to_nodes:
            if target not in self.edges[from_node]:
                self.edges[from_node].append(target)
            if target not in self.in_edges:
                self.in_edges[target] = set()
            self.in_edges[target].add(from_node)

    def run_parallel(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes a list of agent calls in parallel.
        
        Args:
            tasks: List of dicts, each containing:
                - 'name': str, an identifier for the task/agent.
                - 'func': Callable, the agent's run function.
                - 'args': tuple, arguments to pass to the function.
                - 'kwargs': dict, keyword arguments for the function.
        Returns:
            Dict mapping task 'name' to the result of the function execution.
        """
        future_to_name = {}
        results = {}

        for task in tasks:
            name = task.get("name")
            func = task.get("func")
            args = task.get("args", ())
            kwargs = task.get("kwargs", {})
            
            if not func or not name:
                logger.error(f"Invalid task definition: {task}")
                continue
                
            future = self.executor.submit(func, *args, **kwargs)
            future_to_name[future] = name

        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            try:
                result = future.result()
                results[name] = result
            except Exception as exc:
                logger.error(f"Agent task {name} generated an exception: {exc}")
                results[name] = {"error": str(exc)}
                
        return results

    def run_sequential(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes a list of agent calls sequentially.
        """
        results = {}
        for task in tasks:
            name = task.get("name")
            func = task.get("func")
            args = task.get("args", ())
            kwargs = task.get("kwargs", {})
            
            if not func or not name:
                logger.error(f"Invalid task definition: {task}")
                continue
                
            try:
                result = func(*args, **kwargs)
                results[name] = result
            except Exception as exc:
                logger.error(f"Agent task {name} generated an exception: {exc}")
                results[name] = {"error": str(exc)}
                break
                
        return results

    def execute(self, start_node: str, initial_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes the registered graph starting from start_node.
        Executes sibling nodes concurrently via ThreadPoolExecutor.
        Passes accumulated outputs to downstream nodes.
        Logs execution via observability and traps node-level errors.
        """
        workflow_session_id = str(uuid.uuid4())
        app_logger.info(f"[Orchestrator] Starting workflow execution from '{start_node}' (session: {workflow_session_id})")

        # Discover all nodes reachable from start_node
        reachable = set()
        queue = [start_node]
        while queue:
            curr = queue.pop(0)
            if curr not in reachable:
                reachable.add(curr)
                for nxt in self.edges.get(curr, []):
                    if nxt not in reachable:
                        queue.append(nxt)

        # Compute in-degree within reachable subgraph
        in_degree = {node: 0 for node in reachable}
        for node in reachable:
            for target in self.edges.get(node, []):
                if target in in_degree:
                    in_degree[target] += 1

        # Start with accumulated state seeded by initial_input
        state: Dict[str, Any] = dict(initial_input) if isinstance(initial_input, dict) else {}

        current_level = [start_node]

        while current_level:
            app_logger.info(f"[Orchestrator] Executing level: {current_level}")
            
            if len(current_level) == 1:
                node_name = current_level[0]
                node_func = self.nodes.get(node_name)
                start_time = time.time()
                
                if node_func:
                    try:
                        # Prepare input for start_node: pass merged state with initial_input node data if present
                        if node_name == start_node and node_name in initial_input and isinstance(initial_input[node_name], dict):
                            node_input = {**state, **initial_input[node_name]}
                        else:
                            node_input = state
                            
                        app_logger.info(f"[Orchestrator] Running node: {node_name}")
                        result = node_func(node_input)
                        state[node_name] = result
                        latency_ms = (time.time() - start_time) * 1000
                        AgentTracker.log_run(agent_id=node_name, session_id=workflow_session_id, status="success", latency_ms=latency_ms)
                    except Exception as exc:
                        latency_ms = (time.time() - start_time) * 1000
                        logger.error(f"[Orchestrator] Node {node_name} failed: {exc}", exc_info=True)
                        state[node_name] = {"error": str(exc)}
                        AgentTracker.log_run(agent_id=node_name, session_id=workflow_session_id, status="error", latency_ms=latency_ms, error_message=str(exc))
                else:
                    logger.warning(f"[Orchestrator] No function registered for node {node_name}")
            else:
                # Parallel execution for sibling nodes
                tasks = []
                for node_name in current_level:
                    node_func = self.nodes.get(node_name)
                    if node_func:
                        tasks.append({
                            "name": node_name,
                            "func": node_func,
                            "args": (state,),
                            "kwargs": {}
                        })

                batch_start = time.time()
                batch_results = self.run_parallel(tasks)
                batch_latency = (time.time() - batch_start) * 1000

                for node_name, result in batch_results.items():
                    state[node_name] = result
                    status = "error" if isinstance(result, dict) and "error" in result else "success"
                    err_msg = result.get("error") if status == "error" else None
                    AgentTracker.log_run(agent_id=node_name, session_id=workflow_session_id, status=status, latency_ms=batch_latency, error_message=err_msg)

            # Determine next level
            next_level = []
            for node_name in current_level:
                for target in self.edges.get(node_name, []):
                    if target in in_degree:
                        in_degree[target] -= 1
                        if in_degree[target] == 0:
                            next_level.append(target)

            current_level = next_level

        app_logger.info(f"[Orchestrator] Workflow execution completed for session: {workflow_session_id}")
        return state

# Global instance for easy importing
orchestrator = Orchestrator()


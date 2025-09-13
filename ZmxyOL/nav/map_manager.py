"""
地图管理器
管理环境(Env)和位置(Loc)的层级关系，支持路径查找和导航
"""

from typing import Dict, Optional, Callable, Any, List
import numpy as np
from scipy.sparse.csgraph import floyd_warshall



class Loc:
    """位置类"""
    def __init__(self, env: str|list[str], name: str, identifier: Any):
        self.name = name
        self.identifier = identifier  # 标识物，用于确认当前位置
        self.envs: list['Env'] = [mm.envs[env]] if not isinstance(env, list) else [mm.envs[e] for e in env] # 所属的环境
        mm.add_loc(self)

    def __repr__(self):
        return f"L({self.name})"
    
    def loc(self) -> "Loc":
        return self
    
    def env(self) -> "Env":
        # 如果当前位置环境属于该 loc 的所属环境，优先返回当前环境
        env_names = [e.name for e in self.envs]
        if mm.cur_env in env_names:
            return mm.envs[mm.cur_env]
        # 否则根据路由选择最近的环境
        nearest = mm.get_nearest_env(env_names)
        return mm.envs[nearest]
    

class Env:

    """环境类"""
    def __init__(self, name: str, identifier: Any = None):
        self.name = name
        self.identifier = identifier  # 环境标识物
        self.locs: Dict[str, Loc] = {}  # name -> Loc对象
        mm.add_env(self)
    
    def add_loc(self, loc: Loc) -> Loc:
        """添加位置"""
        self.locs[loc.name] = loc
    
    def loc(self) -> Loc:
        return self.locs[self.name]
    
    def env(self) -> "Env":
        return self
    
    def get_all_locs(self) -> list[Loc]:
        """获取所有位置"""
        return list(self.locs.values())
    
    def get_loc_id(self, env_str) -> int:
        return self.get_all_locs().index(self.locs[env_str])
    
    def get_loc_name(self, idx) -> str:
        return self.get_all_locs()[idx].name

    
    def __repr__(self):
        return f"E({self.name})"
    

def get_env_id(env_name: str)->int:
    return list(mm.envs.keys()).index(env_name)

def get_env_name(env_id: int)->str:
    if env_id == -9999: return None
    return list(mm.envs.values())[env_id].name


class MapManager:
    """地图管理器"""
    def __init__(self):
        self.envs: Dict[str, Env] = {}  # name -> Env对象
        self.locs: Dict[str, Loc] = {}  # name -> Loc对象
        self.paths: Dict[tuple, Callable] = {}  # (from, to) -> path_func
        self.env_matrix: List[List[Env]] = []
        self.cur_env: Optional[str] = None
        self.cur_loc: Optional[str] = None
        self.env_predecessors: List[List[int]] = None
        self.env_matrix: List[List[int]] = None
        self.loc_predecessors: Dict[List[List[int]]] = {}
        self.loc_matrix: Dict[List[List[int]]] = {}

    def add_env(self, env: Env) -> Env:
        """添加环境"""
        self.envs[env.name] = env
        self.locs[env.name] = Loc(env.name, env.name, env.identifier)
    
    def add_loc(self, loc: Loc) -> Loc:
        """添加位置"""
        self.locs[loc.name] = loc
        for env in loc.envs:
            self.envs[env.name].add_loc(loc)

    def register_path(self, from_loc: str, to_loc: str):
        """路径装饰器"""
        def decorator(path_func: Callable):
            self.paths[(from_loc, to_loc)] = path_func
            return path_func
        return decorator
    
    def get_envs_path_matrix(self):
        matrix = np.zeros((len(mm.envs), len(mm.envs)))
        for way in self.paths.keys():
            if all(way[i] in self.envs.keys() for i in range(2)):
                matrix[get_env_id(way[0]), get_env_id(way[1])] = 1
        return matrix

    def get_locs_path_matrix(self, env_str:str):
        env = self.envs[env_str]
        env_locs = env.get_all_locs()
        matrix = np.zeros((len(env_locs), len(env_locs)))
        for way in self.paths.keys():
            if all(way[i] in env.locs for i in range(2)):
                matrix[env.get_loc_id(way[0]), env.get_loc_id(way[1])] = 1
        return matrix

    def prepare_route(self):
        self.env_matrix, self.env_predecessors = floyd_warshall(self.get_envs_path_matrix(),directed=True,return_predecessors=True)
        for env_name in self.envs.keys():
            self.loc_matrix[env_name], self.loc_predecessors[env_name] = floyd_warshall(
                self.get_locs_path_matrix(env_name),directed=True,return_predecessors=True
            )

    def get_nearest_env(self, envs: str|list[str]) -> str:
        from ZmxyOL.nav.api import locate_region
        if self.env_predecessors is None: self.prepare_route()
        if not isinstance(envs, list): return envs
        if not self.cur_env: locate_region()
        cur_env_id = get_env_id(self.cur_env)
        idx = 0
        for i, env in enumerate(envs):
            if env not in self.envs.keys(): env = mm.locs[env].env().name
            env_id = get_env_id(env)
            if self.env_matrix[cur_env_id, env_id] < self.env_matrix[cur_env_id, idx]:
                idx = i
        return envs[idx]

    def _find_route(self, predecessors, from_id, to_id) -> Optional[list[int]]:
        """
        根据给定的起点和终点，计算并返回最短路径的路由列表。

        Args:
            start (str): 起始环境（地点）的名称。
            end (str): 目标环境（地点）的名称。

        Returns:
            list[tuple[int, int]]: 一个表示路径边的列表，例如 [(1, 7), (7, 4)]。
                                如果无法到达或输入无效，则返回一个包含错误信息的字符串。
                                如果起点和终点相同，则返回一个空列表。
        """

        # 如果起点和终点相同，无需移动
        if from_id == to_id:
            return []

        # 检查是否存在路径
        if predecessors[from_id, to_id] == -9999:
            return f"无法找到从 {from_id} 到 {to_id} 的路径。"

        # 从目标点开始，利用前驱矩阵反向追溯路径
        path_edge_ids = []
        current_id = to_id
        while current_id != from_id:
            prev_id = predecessors[from_id, current_id]
            
            # 安全检查，防止路径中断
            if prev_id == -9999:
                return f"路径构建中断：从 {from_id} 到 {to_id} 的路径不完整。"
            
            # 将边（元组）添加到路径列表的前端
            path_edge_ids.insert(0, (prev_id, current_id))
            
            # 更新当前节点为前一个节点，继续追溯
            current_id = prev_id
                
        return path_edge_ids

    def find_env_route(self, start: str, end: str) -> Optional[list[str]]:
        """根据给定的起点和终点，计算并返回最短路径的路由列表。"""
        from_id = get_env_id(start)
        to_id = get_env_id(end)
        path_edge_ids = self._find_route(mm.env_predecessors, from_id, to_id)
        path_edges = [(get_env_name(prev_id), get_env_name(current_id)) for prev_id, current_id in path_edge_ids]
        return path_edges
    
    def find_loc_route(self, env_name:str, start: str, end: str) -> Optional[list[str]]:
        """根据给定的起点和终点，计算并返回最短路径的路由列表。"""
        cur_region, cur_loc = mm.get_region()
        mm.set_region(env_name, start)
        start_loc, end_loc = mm.locs[start], mm.locs[end]
        start_env, end_env = start_loc.env(),end_loc.env()
        assert start_env.name == end_env.name and end_env.name == env_name, f"起{start_env.name},止{end_env.name},{env_name}不匹配"
        env = mm.envs[env_name]
        from_id, to_id = env.get_loc_id(start),env.get_loc_id(end)
        path_edge_ids = self._find_route(mm.loc_predecessors[env_name], from_id, to_id)
        assert isinstance(path_edge_ids, list), path_edge_ids
        path_edges = [(env.get_loc_name(prev_id), env.get_loc_name(current_id)) for prev_id, current_id in path_edge_ids]
        mm.set_region(cur_region, cur_loc)
        return path_edges
        
    def navigate_to(self, cur_env: str, cur_loc: str, tar_env: str, tar_loc: str) -> str:
        """执行导航"""
        route = []
        if cur_loc == tar_loc: return
        # 同env，直接小路由
        if cur_env == tar_env:
            route.extend(self.find_loc_route(cur_env, cur_loc, tar_loc))
        else:# 不同env，直接小路由+大路由+小路由
            if cur_env != cur_loc:
                route.extend(self.find_loc_route(cur_env,cur_loc, cur_env))
            route.extend(self.find_env_route(cur_env, tar_env))
            if tar_env != tar_loc:
                route.extend(self.find_loc_route(tar_env, tar_env, tar_loc))


        for from_env, to_env in route:
            self.paths[(from_env, to_env)]()

        self.set_region(tar_env, tar_loc)
        return
        
    
    def set_region(self, env: str, loc: str=None):
        """设置当前位置"""
        self.cur_env = env
        self.cur_loc = loc if loc else env
        return self.get_region()
    
    def set_loc(self, loc:str):
        self.cur_loc = loc
        return self.get_region()
    
    def get_region(self) -> tuple[Optional[str], Optional[str]]:
        """获取当前位置"""
        return self.cur_env, self.cur_loc


# 全局地图管理器实例
mm = MapManager()


# 路径装饰器
def path(from_locs: str|list[str], to_locs: str|list[str]):
    """路径装饰器，用于注册从from_loc到to_loc的路径函数"""
    from ZmxyOL.nav.envs.decorators import LOC_ENV
    def decorator(path_func):
        from_locs_list = [from_locs] if isinstance(from_locs, str) else from_locs
        to_locs_list = [to_locs] if isinstance(to_locs, str) else to_locs
        
        # 处理特殊环境情况
        if from_locs == LOC_ENV:
            from_locs_list = [e.name for e in mm.locs[to_locs_list[0]].envs]
        if to_locs == LOC_ENV:
            to_locs_list = [e.name for e in mm.locs[from_locs_list[0]].envs]
            
        for from_loc in from_locs_list:
            for to_loc in to_locs_list:
                if from_loc != to_loc:
                    mm.register_path(from_loc, to_loc)(path_func)
        
        return path_func
    return decorator 
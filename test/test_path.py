from AutoScriptor import *
from ZmxyOL.nav import *
import numpy as np
from scipy.sparse.csgraph import floyd_warshall
import pandas as pd
for env in mm.envs.values():
    print(f"{env}")
    for loc in env.locs.values():
        print(f"    {loc}")

ways = mm.paths.keys()
node = mm.envs.keys()

def get_env_id(env_name: str)->int:
    return list(mm.envs.keys()).index(env_name)

def get_env_name(env_id: int)->Env:
    if env_id == -9999: return None
    return list(mm.envs.values())[env_id].name

def get_path_matrix()->list[list[Env]]:
    matrix = np.zeros((len(mm.envs), len(mm.envs)))
    for way in ways:
        matrix[get_env_id(way[0]), get_env_id(way[1])] = 1
    return matrix
adjacency_matrix = get_path_matrix()
print(adjacency_matrix)
_, env_predecessors = floyd_warshall(adjacency_matrix,directed=True,return_env_predecessors=True)
print(env_predecessors)

mat = pd.DataFrame([[get_env_name(env_predecessors[i][j]) for j in range(len(env_predecessors[i]))] for i in range(len(env_predecessors))],index=mm.envs.keys(),columns=mm.envs.keys())
print(mat)
        
def get_navigation_route(from_env: str, to_env: str) -> list[tuple[str, str]]:
    """
    根据给定的起点和终点，计算并返回最短路径的路由列表。

    Args:
        from_env (str): 起始环境（地点）的名称。
        to_env (str): 目标环境（地点）的名称。

    Returns:
        list[tuple[str, str]]: 一个表示路径边的列表，例如 [('村庄', '天庭'), ('天庭', '极北')]。
                               如果无法到达或输入无效，则返回一个包含错误信息的字符串。
                               如果起点和终点相同，则返回一个空列表。
    """

    from_id = get_env_id(from_env)
    to_id = get_env_id(to_env)

    # 如果起点和终点相同，无需移动
    if from_id == to_id:
        return []

    # 检查是否存在路径
    if env_predecessors[from_id, to_id] == -9999:
        return f"无法找到从 {from_env} 到 {to_env} 的路径。"

    # 从目标点开始，利用前驱矩阵反向追溯路径
    path_edges = []
    current_id = to_id
    while current_id != from_id:
        prev_id = env_predecessors[from_id, current_id]
        
        # 安全检查，防止路径中断
        if prev_id == -9999:
             return f"路径构建中断：从 {from_env} 到 {to_env} 的路径不完整。"

        # 获取边的起点和终点名称
        prev_name = get_env_name(prev_id)
        current_name = get_env_name(current_id)
        
        # 将边（元组）添加到路径列表的前端
        path_edges.insert(0, (prev_name, current_name))
        
        # 更新当前节点为前一个节点，继续追溯
        current_id = prev_id
            
    return path_edges

for from_env in mm.envs.values():
    print(f"{from_env.name}:")
    for to_env in mm.envs.values():
        if from_env.name == to_env.name:
            continue
        print(f"{from_env.name} -> {to_env.name}: {get_navigation_route(from_env.name, to_env.name)}")
# Spring Bone 公式证据

复核日期：2026-10-23。同日补入第 9 节索引。本文只记录已打开的来源、从这些来源推出的式子，以及尚未核过的边界。没有运行时数值试验。没有把 Unreal 源码复制进插件。行号按各文件的 `splitlines()` 计数，空行计入，行尾换行不另算一行。Git blob 的 SHA-1 与字节数来自 GitHub Contents API；SHA-256 由本轮对 API 返回的原始字节计算。本地 UE 文件的 SHA-256 由本轮对磁盘字节计算。

硬门顺序：来源明确，事实可核，关联清楚，推导可追，结论可证。某一级没有通过时，停在该级，不写成下一级结论。

状态词：

- 已核：本轮读到了所引行或 API 字段。
- 推导：只由已核式子做代数展开，没有数值对照。
- 未核：目录或名字已出现，正文未读完，或没有运行样本。
- 撤回：上一轮对话里的说法，本档不再当作事实。

## 1. 来源

| 编号 | 来源 | 本轮钉住的版本 | 用途 |
| --- | --- | --- | --- |
| S1 | `vrm-c/vrm-specification` | API 报告的 `master` = `94e82dd346fa6cf0337c4421728640e5252dd38e`（2026-10-02，提交说明为合并 `VRMC_springBone_limit`） | 规格 |
| S2 | `specification/VRMC_springBone-1.0/README.md` | commit `94e82dd` 的 blob `eee0164d2bd4c6cd916c3cc3d818f1608f3b1931`，20106 字节，594 行，SHA-256 `ee7108a44ce9bf16ac0b049ad98a0ecfb64d6556ee56c5088b74bc68241c4c21` | 惯性、碰撞、旋转、center |
| S3 | `specification/VRMC_springBone_limit-1.0/README.md` | 同 commit，blob `39998181a2f02f85b6134c01f965afa9c189b52b`，19377 字节，551 行，SHA-256 `b2e41827c429c7bc0bf53a66e5e063d92ebc1177e2857da4a4c4a490cf034571` | 锥、铰、球限制 |
| S4 | `specification/VRMC_springBone_extended_collider-1.0/README.md` | 同 commit，blob `9afcf4ecc56343677e8695801bcb7163b476c6d8`，14727 字节，468 行，SHA-256 `ac053955493f1d9cd14c564eb36d5562984ffe4627bf6c682f6698e7d08228a2` | 内部球、内部胶囊、平面 |
| A1 | `saturday06/VRM-Addon-for-Blender` `src/io_scene_vrm/editor/spring_bone1/handler.py` | commit `2efbdfc2b91bd041dda68782d8a36422527c8d36` 的 blob `dca505168447964c3c42ba4fce42fa74f2b60025`，36948 字节，994 行，SHA-256 `4aedfa5f5394ef7c9cad5477a605b6d665e061c348781eec45b1c24fe1faca41` | Blender 侧积分 |
| A2 | 同仓库 `src/io_scene_vrm/blender_manifest.toml` | 同一 commit，blob `efd16a4ab6695a12b7b019113ef9c2a717fd60e2`，522 字节。`version = "4.10.2"`，`blender_version_min = "4.2.0"`，`blender_version_max = "5.3.0"` | 版本与整包许可证字段 |
| A3 | 同仓库 `src/io_scene_vrm/editor/spring_bone1/property_group.py` | 同一 commit，blob `5ec1200ff865f8f627c01105bc6dd97fa7ae47d0`，55197 字节，1457 行，SHA-256 `abce7d1bf49545f7b983aa846fc46205d3bf810521bf070ad4d6931a96aef243` | 关节字段与 `default_rotation` |
| A4 | 同仓库 `src/io_scene_vrm/common/rotation.py` | 同一 commit，blob `f11c05d4720967fd6b679b650f85febd47f8e1b8`，3060 字节。内容开头解码为 SPDX 行 | 旋转读写。函数行号未单列 |
| U1 | `C:\UE5.7.4\Engine\Source\Runtime\Launch\Resources\Version.h` | 7029 字节，99 行，SHA-256 `c6cdaf48638ec9b24073a13b5115455d02ec9998ecb89b979b1081409a126ef8`。版本宏在第 58–60 行，第 67 行 `static_assert` | 引擎版本 |
| U2 | `C:\UE5.7.4\Engine\Source\Runtime\AnimGraphRuntime\Private\BoneControllers\AnimNode_SpringBone.cpp` | 8935 字节，272 行，SHA-256 `d5a760b56590e8c2c95be801bb3784b028535ef5dd4d8775465031ee921ab449` | UE 弹簧骨积分 |
| U3 | 同目录 `AnimNode_SpringBone.h` | 4883 字节，131 行，SHA-256 `11b7e350dd50a840e86750a9b625b6184b02f2ad33a290cfcc4f583d97db1c21` | 参数默认值与成员含义 |
| U4 | `AnimNode_AnimDynamics.h`；`AnimPhysicsSolver.h`；`AnimPhysicsSolver.cpp` | 分别 31540 字节 / 687 行 / `30e1df8aa43f31775936a78570d5ef8cc848270ea45ea35332f4263169219823`；24930 字节 / 624 行 / `9a2357610cfeffec7249db491c2fdc094adf098259bf337b8c317bc1a04d2b13`；43764 字节 / 1113 行 / `1973f6670229aaa06bfdfa08dec950aca2b70f7665b7c86d60784c027ff2f582` | 只确认文件存在。积分未抄 |

S2 写明 “SpringBone Algorithm” 一节 **non-normative**。S3 的限制参考实现同样写明 **non-normative**。因此 S2/S3 的伪代码是参考实现，不是互操作的规范性字节级要求。

## 2. 撤回的上一轮说法

以下句子不再作为事实使用。

1. “支持 Blender 2.93 到 5.1”。A2 当前声明是 `blender_version_min = "4.2.0"`、`blender_version_max = "5.3.0"`。更早仓库简介里的版本范围本轮没有再打开，不能并列成现行事实。
2. “参数模型和 Unity DynamicBone 是同一类”。本轮没有打开 DynamicBone 源码或公开公式。名字相近不构成公式相同。
3. “整个 VRM 插件可以按 MIT 搬进本仓库”。已核 SPDX 的只有 A1 第 1 行、A3 第 1 行、A4 内容开头，以及 A2 的 `license = ["SPDX:MIT", "SPDX:GPL-3.0-or-later"]`、`copyright = ["2020 Isamu Mogi", "2018 iCyP"]`。`spring_bone1` 目录里其余文件本轮只记录了 blob，没有读 SPDX。
4. “UE 弹簧骨可以直接当移植源码”。U2 第 1 行与 U1 第 77 行均为 `Copyright Epic Games, Inc. All Rights Reserved.` 本轮没有阅读完整 EULA。公式可以引用；源码拷贝不在本档授权范围内。

## 3. VRM 规格式（S2，已核的伪代码）

惯性，规格自称为 verlet integration：

```
inertia   = (currentTail - prevTail) * (1 - dragForce)
stiffness = deltaTime * parentWorldRotation * initialLocalRotation * boneAxis * stiffnessForce
external  = deltaTime * gravityDir * gravityPower
nextTail  = currentTail + inertia + stiffness + external
nextTail  = worldPosition + normalize(nextTail - worldPosition) * boneLength
```

碰撞，`distance < 0` 时：

```
nextTail = nextTail - direction * distance
nextTail = worldPosition + normalize(nextTail - worldPosition) * boneLength
```

球：

```
distance  = |nextTail - transformedOffset| - collider.radius - jointRadius
direction = normalize(nextTail - transformedOffset)
```

胶囊：把 `delta` 投到胶囊轴段上再算同样的 `distance`。本档摘录了该分支结构，没有逐行抄录全部临时变量。

旋转：

```
prevTail = currentTail
currentTail = nextTail
to = normalize(nextTail * inverse(parent.worldMatrix * initialLocalMatrix))
node.rotation = initialLocalRotation * fromToQuaternion(boneAxis, to)
```

center 的定义在 S2 第 191–207 行，全文已读：默认用世界空间；`center` 按 SpringChain 指定一个节点，关节在相对该节点的空间里求值；该节点必须是该链第 0 个关节或其祖先。算法节第 590–594 行只有两句：惯性改在 center space 计算，重力仍在世界空间。这里没有矩阵或伪代码。状态：定义与这两句 **已核**；“如何把世界变换变到 center space”规格没有给出式子。

参数表已核：`hitRadius` 为米；`stiffness` 为 0 或更大；`dragForce` 为 `[0, 1]`；`gravityDir` 为向量；`gravityPower` 为每帧施加的重力项。规格没有给出这些数与质量、胡克系数之间的换算。

## 4. Blender 实现式（A1，blob 已核）

文件内注释指向两个旧规格提交，本轮没有打开这两个提交的正文：

- 第 282 行：`993a90a5bda9025f3d9e2923ad6dea7506f88553` 的 update procedure
- 第 575 行：`7279e169ac0dcf37e7d81b2adcad9107101d7e25` 的 center-space

因此“实现等于它所注释的那个提交”仍是 **未核**。下面只比较 A1 与本轮读到的 S2/S3。

### 4.1 惯性与长度

第 706–723 行：

```
inertia = (current_tail - previous_tail) * (1 - head_joint.drag_force)
stiffness_direction = normalize(
    obj_matrix_world_quaternion
    @ next_head_parent_pose_bone_object_rotation
    @ (inverse(head_rest) @ tail_rest_translation)
)
stiffness = stiffness_direction * delta_time * head_joint.stiffness
external  = gravity_dir * delta_time * head_joint.gravity_power
next_tail = current_tail + inertia + stiffness + external
```

第 729–737 行的长度使用的是当前姿势下头尾世界距离，不是初始化时冻结的 `boneLength`：

```
head_to_tail_world_distance = |(world @ head_pose_translation) - (world @ tail_pose_translation)|
next_tail = head_world + normalize(next_tail - head_world) * head_to_tail_world_distance
```

关联：三项相加的形状与 S2 相同。`drag_force`、`stiffness`、`gravity_power`、`gravity_dir` 与规格字段同名。刚度方向经过归一化，规格伪代码把 `boneAxis` 放在四元数旋转里，本档没有做数值对照，所以“方向向量相等”停在 **推导未闭合**。长度每帧从当前姿势重算，与 S2 初始化状态里的 `boneLength` 不是同一句代码；刚体且无拉伸时两者在代数上可重合，该重合 **未做数值证明**。

### 4.2 时间步

第 855–875 行。场景 `fps` 与 `fps_base` 参与是否再推进一步；通过后

```
delta_time = float((n+1) / 60) - float(n / 60)
```

注释写明不要把 `delta_time` 写成常量 `1/60`。精确算术下该差是 `1/60`。这是实现自己的时钟。S2 只接收调用者给出的 `deltaTime`，没有规定 60 Hz。状态：步长公式 **已核**；“每帧步数等于 `60 * fps_base / fps`”是 **推导**，没有跑过一帧。

### 4.3 碰撞与限制的次序

第 749 行起，对每个碰撞体取 `calculate_collision(next_tail, head_joint.hit_radius)`。`distance >= 0` 则跳过；否则 `next_tail = next_tail - direction * distance`，再做长度约束，再调用 `_apply_spring_bone_limit`。惯性之后、进入碰撞循环之前也会调用一次该限制。第一次调用落在长度约束结束与第 749 行碰撞注释之间，即第 738–747 行。

这与 S3 的句子一致：惯性之后，以及每一次碰撞之后，都对 `nextTail` 做角度限制，并保持弹簧长度。次序 **已核**。

球碰撞类在第 161 行：`distance = |target - offset| - target_radius - radius`，方向为 `normalize(target - offset)`。与 S2 球伪代码同形。胶囊类在第 176 行，最近点夹到轴段 `[0,1]`。与 S2 胶囊分支同形。二者是 **已核的结构对应**，不是逐输入的数值证明。

S4 附录第 404–468 行与 A1 的距离式现在都已读。对应关系：

| 形状 | S4 行 | S4 式 | A1 行 | A1 式 |
| --- | --- | --- | --- | --- |
| 内部球 | 413、416 | `radius - jointRadius - \|delta\|`，方向 `-normalize(delta)`，`delta = nextTail - offset` | 216–227 | `radius - target_radius - \|target - offset\|`，方向 `normalize(offset - target)` |
| 内部胶囊 | 446、449 | 同样的距离与取反方向；轴段投影与 S2 胶囊相同 | 231–267 | 轴段夹到 `[0,1]` 后使用内部球同一距离式 |
| 平面 | 460–467 | `dot(delta, normalize(normalMatrix(world) * normal)) - jointRadius`，方向为该法线 | 278–279、408–413 | 距离 `dot(target - offset, normal) - target_radius`；法线由 `world.to_quaternion() @ localNormal` 得到，构造时没有再归一化 |

内部球、内部胶囊的距离与方向，在 `delta = target - offset` 的定义下与 S4 代数相同。这是 **推导**。平面的法线变换不同：S4 写 `normalMatrixFrom` 后再归一化，A1 只用矩阵的旋转四元数，并保留缩放被丢掉之后的长度。无缩放且局部法线已是单位向量时二者方向相同，这一句同样是 **推导**，没有带缩放的数值样本。

A1 第 375–384 行与第 428–433 行：胶囊两端重合时改用球。S2、S4 的胶囊伪代码没有这一支。这是实现附加分支，**已核**。

世界矩阵作用在 offset 和 tail 上（A1 第 352–371、416–425 行）。半径仍用属性原值，S2 与 S4 的伪代码同样没有把半径乘缩放。

### 4.4 角度限制

S3 要求惯性后和每次碰撞后施加限制。局部空间的正 Y 为限制轴。A1 第 45–113 行实现了三种：

- 锥：`cone_angle` 夹到 `[0, π]`；`direction.y < cos(limit)` 时把水平分量缩放到 `sin(limit)`。
- 铰：投到 YZ 平面；同样用 `cos` 夹角；Z 符号保留。
- 球：`pitch = atan2(z, y)`，`yaw = asin(x)`；pitch 夹到 `±spherical_pitch`，yaw 夹到 `±spherical_yaw`；再写回 `(sin yaw, cos yaw cos pitch, cos yaw sin pitch)`。

与 S3 伪代码同形的部分 **已核**。字面差异也已核，因此不能写成逐字相同：

- A1 先 `normalize`，并用 `x^2+z^2` 作为水平长度；S3 锥限制用 `1 - y^2`，并声明 `tailDir` 已是单位向量。单位向量上二者代数相等，**推导**，无数值样本。
- A1 用 `float_info.epsilon` 处理近奇异方向；S3 用 `y == -1` 与 `abs(x) == 1`。谓词不同。数值是否等价 **未核**。
- `default_rotation` 在 A3 第 1092–1098 行，是 `@staticmethod`。S3 第 431–437 行：`dot == -1` 时 `Quaternion(1, 0, 0, 0)`，注释写明绕 X 轴 180 度；否则 `Quaternion(boneAxis.z, 0, -boneAxis.x, dot + 1)`，第 436 行注释写明参数是叉积再加标量。A3 在 `dot < -1 + epsilon` 时返回 `Quaternion((0, 1, 0, 0))`，否则返回 `Quaternion((dot + 1, bone_axis.z, 0, -bone_axis.x))`。2026-10-23 打开的 `https://docs.blender.org/api/current/mathutils.html` 写明四元组序列是 `(w, x, y, z)`。按该页，插件的 WXYZ 与规格注释里的 xyzw 是同一分量；奇异分支也是 w=0、x=1。该文档 URL 是 `current`，没有钉在 Blender 4.2。谓词仍不同：规格是精确等于 -1，插件是夹紧到 `[-1,1]` 后再与 `-1 + epsilon` 比较。数值差 **未核**。

### 4.5 旋转写回

第 788–793 行用局部头尾向量的叉积和夹角构造 `mathutils.Quaternion`。这与 S2 的 `fromToQuaternion` 在两向量非共线时是同一几何对象，**推导**。叉积为零时 `Quaternion` 的行为 **未核**。

### 4.6 center 平移

第 543–553 行与第 699–703 行：若启用 center，且 center 是链首骨骼的祖先（第 576–582 行），则把 `current_center - previous_center` 同时加到 `previous_tail` 和 `current_tail` 上，再算惯性。

推导：同一平移加到两项上，相减后抵消，所以这一步只从惯性位移里去掉 center 的平移。重力项第 723 行仍直接使用 `gravity_dir`，与 S2 第 594 行“重力在世界空间”一致。S2 第 197–198 行要求在相对 center 节点的空间里求值，第 592–593 行没有给出旋转或矩阵。A1 没有把尾点乘 center 旋转的逆。平移抵消 **已由代码推出**。“完整实现了 center space” **不可证**，因为规格自己没有把该空间的变换写成式子，代码也只处理了平移差。

## 5. UE 5.7.4 弹簧骨式（U2、U3，已核）

节点是 `FAnimNode_SpringBone`。默认值在 cpp 第 16–19 行：`MaxDisplacement = 0`，`SpringStiffness = 50`，`SpringDamping = 4`，`ErrorResetThresh = 256`。头文件第 32–37 行把前三个暴露为刚度、阻尼和超长重置阈值。没有质量参数，没有 `dragForce`，没有 `hitRadius`，没有碰撞体列表。

第 62–63 行：

```
RemainingTime += Context.GetDeltaTime()
FixedTimeStep = (1/120) * TimeDilation
```

注释写 “Fixed step simulation at 120hz”。`TimeDilation != 1` 时步长不是 `1/120`。`GetDeltaTime()` 是否已经乘过时间膨胀，**未核**。

第 139–189 行，每个固定步：

```
Error        = TargetPos - BoneLocation
DampingForce = SpringDamping * BoneVelocity
SpringForce  = SpringStiffness * Error
Acceleration = SpringForce - DampingForce

若 SpringDamping > 1/FixedTimeStep:
    BoneVelocity += (1/FixedTimeStep) / SpringDamping * Acceleration * FixedTimeStep
否则:
    BoneVelocity += Acceleration * FixedTimeStep

BoneLocation += BoneVelocity * FixedTimeStep
```

其后按轴过滤平移，可选地把位移投影回半径 `MaxDisplacement` 的球，然后用投影后的位移重写速度：

```
BoneVelocity = (BoneLocation - OldBoneLocation) / FixedTimeStep
```

推导：积分顺序是先更新速度、再用新速度更新位置，即半隐式欧拉。加速度没有除以质量，等价于把 `m = 1` 放进 `a = k x - c v`。阻尼大于 `1/dt` 时的缩放、速度模长相对 `ErrorResetThresh` 的夹紧、以及投影后重写速度，都是离散保护，不属于连续方程 `a = kx - cv`。状态：连续式是 **推导**；这些保护分支是 **已核代码**。

`TargetPos` 与 `BoneLocation` 在世界空间（第 112–120 行）。输出平移用组件变换的逆变换回到组件空间（第 196–204 行）。

旋转在第 206–221 行可选。`AdditionalRotation = FindBetweenNormals(ParentToTarget, ParentToCurrent)`，其中 `TargetPos`、`BoneLocation` 是世界空间，`ParentSpaceBase.GetLocation()` 来自 `GetComponentSpaceTransform`。减数与被减数的空间来源不一致。本档没有运行样本，因此不把它写成已证实缺陷；后续若依赖该旋转，必须先核对这一减式。欧拉角过滤在同一段，过滤后的欧拉再乘回原旋转。

`PreUpdate` 第 251–266 行：只有 `bOverrideOwnerVelocity` 时使用覆盖速度；否则仅当组件有父级且自身 Owner 为空时，才取父级 Owner 的速度；其余路径把 `OwnerVelocity` 设为零。头文件第 50 行的成员注释是 “Velocity of the owning actor”。注释与这条赋值路径不是同一句话。普通带 Owner 的骨骼网格上，代码写入的是零向量。这是 **已核**。第 128–130 行仍会做 `BoneLocation += OwnerVelocity * FixedTimeStep`；速度为零时该项为零。

## 6. 两边公式的关联

只比较本档已经写下的式子。

| 项 | VRM 规格 S2 与 A1 | UE U2 | 可下的结论 |
| --- | --- | --- | --- |
| 状态 | 尾点的 `prevTail`、`currentTail` | 骨骼世界位置与世界速度 | 状态变量不同 |
| 连续/离散原型 | `(current-prev)*(1-drag) + dt*刚度方向 + dt*重力`，再投影到骨长 | `a = k*误差 - c*速度`，半隐式欧拉，固定步 | 不是同一个递推 |
| 刚度 | 沿静息骨方向加一段 `dt * stiffness` 位移 | `k * (目标位置 - 当前位置)` | 同名参数不能互换 |
| 阻尼 | `dragForce` 缩放上一帧位移，范围 `[0,1]` | `SpringDamping` 乘速度，默认 4，可大于 1 | 没有已证的换算 |
| 重力 | `dt * gravityDir * gravityPower` | 此节点代码中没有单独重力项 | UE 该节点不含这项 |
| 约束 | 骨长投影；可选角度限制；球/胶囊碰撞 | 可选位移球、轴向过滤、误差重置 | 约束集合不同 |
| 步长 | A1 按约 60 Hz 推进 | U2 按 `(1/120)*TimeDilation` | 步长不同 |
| 作用对象 | 由尾点反推骨骼旋转 | 默认改平移；旋转是另一条可选路径 | 输出量不同 |

结论，且只到这一句：二者都是单骨骼链上的二次运动，方程不同。不存在本档已证明的参数映射。把 VRM 的 `stiffness` 填进 UE 的 `SpringStiffness`，或把 `dragForce` 当成 `SpringDamping`，都没有公式依据。

`FAnimNode_AnimDynamics` 与 `FAnimPhys` 在 U4 中存在。本档没有抄它们的积分。它们不能用来证明或否定第 5 节的式子。

## 7. 后续可以依靠的结论

通过硬门、可以引用的：

1. A1 在 commit `2efbdfc2`、blob `dca50516` 的惯性三项是第 706–723 行，许可证行是第 1 行。
2. A1 第 172、212 行的外球、外胶囊距离式与 S2 第 537、568 行同形；限制调用时机与 S3 第 154–155 行、第 401–402 行一致。
3. 内部球与内部胶囊的距离、方向与 S4 第 413、416、446、449 行代数相同。平面法线构造不相同，见第 4.3 节。
4. 本地 UE 5.7.4、U2 SHA-256 `d5a760b5…` 的 `EvaluateSkeletalControl_AnyThread`（第 95–228 行）实现第 5 节的半隐式欧拉。
5. 第 6 节的表：VRM 式与 UE 式不能互相代换。

没有通过、不能引用为事实的：

- 与 Unity DynamicBone 的公式异同。
- `spring_bone1` 中尚未读 SPDX 的文件能否按 MIT 并入。
- A1 是否字节级符合注释里的旧规格提交 `993a90a5`、`7279e169`，以及 A3 第 1116 行指向的 `6fb6baaf` beta schema。
- center space 的完整变换。规格没有式子，A1 只抵消了平移。
- 刚度方向、锥限制水平长度、奇异角谓词的数值等价。
- 平面在非均匀缩放下与 S4 `normalMatrixFrom` 是否同向。
- UE 旋转减式是否在实际组件变换下出错。
- `GetDeltaTime()` 与 `TimeDilation` 的重复缩放关系。
- 任何一帧的屏幕结果或误差数。本档没有运行 Blender，也没有运行 Unreal。

## 8. 若要进入实现

实现前只从第 7 节“可以通过”的条目取式。若目标是 VRM 兼容的二次运动，积分应沿 A1 第 706–737 行和 S2 伪代码，而不是沿 U2。UE 源码在这里的角色是对照，用来避免把 `SpringStiffness` / `SpringDamping` 误当成 VRM 参数。

移植 `handler.py` 时保留第 1 行 SPDX 与 A2 中的版权人。A3、A4 已核到同一 SPDX 表达式。`spring_bone1` 目录中其余文件先读各自 SPDX，再决定能否放进本仓库。UE 的 cpp 不进入本仓库。

## 9. 详细索引

本节是跳转表。公式含义仍以第 3–6 节为准。旧提交 `993a90a5`、`7279e169`、`6fb6baaf` 只出现在源码注释里，本轮没有打开它们的正文。

### 9.1 规格标题

S2，594 行：

| 行 | 标题或式 |
| --- | --- |
| 191–193 | Evaluation Space；默认世界空间 |
| 195–207 | Center Space 的节点约束 |
| 392–428 | 关节字段示例与参数表。`hitRadius` 第 424 行，`stiffness` 第 425 行，`gravityPower` 第 426 行，`gravityDir` 第 427 行，`dragForce` 第 428 行 |
| 430–432 | SpringBone Algorithm，non-normative |
| 436 | 点名 UniVRM 与 three-vrm 为其它实现。这两个仓库本轮没有打开 |
| 440–444 | 从祖先到后代的更新顺序 |
| 450–458 | `SpringBoneJointState` |
| 488–503 | 惯性与骨长。式在第 496–503 行 |
| 514–525 | 碰撞推开与再次约束骨长。式在第 520–523 行 |
| 532–541 | 外球。距离式第 537 行 |
| 547–572 | 外胶囊。距离式第 568 行 |
| 580–587 | 写回旋转。式在第 582–587 行 |
| 590–594 | center space 下的惯性与世界空间重力。无矩阵 |

S3，551 行：

| 行 | 标题或式 |
| --- | --- |
| 150–155 | 限制施加顺序：惯性后，以及每次碰撞后 |
| 392 | 附录 non-normative |
| 397–406 | 同一顺序的重复说明 |
| 413 | `tailDir = normalize(nextTail - joint.worldPosition)` |
| 424–451 | 限制空间旋转。奇异分支第 431–433 行，一般分支第 437 行 |
| 453–476 | 锥。夹角第 459 行，`1 - y^2` 第 465 行 |
| 482–509 | 铰。投影第 490–496 行，Z 符号第 504 行 |
| 511–551 | 球。`atan2` 第 529 行，`asin` 第 531 行，重建第 546 行 |

S4，468 行：

| 行 | 标题或式 |
| --- | --- |
| 83–100 | 三种扩展碰撞的文字定义 |
| 398 | 附录 non-normative |
| 408–416 | 内部球。距离第 413 行，方向第 416 行 |
| 425–449 | 内部胶囊。距离第 446 行，方向第 449 行 |
| 458–467 | 平面。法线第 460 行，距离第 464 行，方向第 467 行 |

### 9.2 插件符号

A1 函数：

| 行 | 符号 | 索引内容 |
| --- | --- | --- |
| 1 | SPDX | `MIT OR GPL-3.0-or-later` |
| 45–113 | `_apply_spring_bone_limit_local_direction` | 锥、铰、球的局部方向 |
| 119–149 | `_apply_spring_bone_limit` | 把局部限制变回世界尾点 |
| 161–172 | `SphereWorldCollider.calculate_collision` | 外球返回式第 172 行 |
| 176–212 | `CapsuleWorldCollider.calculate_collision` | 外胶囊返回式第 212 行 |
| 216–227 | `SphereInsideWorldCollider.calculate_collision` | 内部球返回式第 227 行 |
| 231–267 | `CapsuleInsideWorldCollider.calculate_collision` | 内部胶囊返回式第 267 行 |
| 271–279 | `PlaneWorldCollider.calculate_collision` | 平面距离第 278 行 |
| 282 | 注释 | 指向规格提交 `993a90a5` 的 update procedure |
| 347–414 | 扩展碰撞构造 | 内部形状按 `inside` 分支；平面法线第 408–410 行 |
| 415–441 | 基础球与胶囊构造 | 两端重合时退化为球，第 428–433 行 |
| 492 | `_calculate_spring_pose_bone_rotations` | 弹簧循环入口 |
| 543–553 | center 平移差 | 无 center 时差为零 |
| 575 | 注释 | 指向规格提交 `7279e169` 的 center-space |
| 576–582 | `enable_center_space` | center 必须是链首的祖先 |
| 633 | `_calculate_joint_pair_head_pose_bone_rotations` | 单段关节 |
| 706–708 | `inertia` | `(current - previous) * (1 - drag_force)` |
| 717–723 | 刚度与重力 | 方向归一化后乘 `delta_time * stiffness`；重力第 723 行 |
| 725–737 | 尾点与骨长 | 骨长取当前姿势头尾距离，第 729 行 |
| 749–764 | 碰撞循环 | `distance >= 0` 跳过；推开后再次限制 |
| 788–793 | 头骨骼旋转 | 叉积与夹角 |
| 835–881 | `frame_change_pre` | 60 Hz 步长。`delta_time` 第 875 行 |
| 883 | `sort_spring_bone_joints` | 祖先优先，否则断开成多链 |

A3 关节字段，类 `SpringBone1JointPropertyGroup` 从第 1117 行开始：

| 行 | 字段 | 已读约束 |
| --- | --- | --- |
| 1123–1128 | `hit_radius` | `min=0`，`default=0`，`soft_max=0.5` |
| 1130–1135 | `stiffness` | `min=0`，`default=1`，`soft_max=4` |
| 1137–1142 | `gravity_power` | `min=0`，`default=0`，`soft_max=2` |
| 1152–1160 | `gravity_dir` | `default=(0, 0, -1)`，分量 `[-1, 1]`；第 1144–1150 行把非单位向量归一化，零向量写成 `(0, 0, -1)` |
| 1162–1167 | `drag_force` | `default=0.5`，`min=0`，`max=1` |
| 1092–1098 | `default_rotation` | 见第 4.4 节 |
| 1116 | 注释 | 指向 `VRMC_springBone-1.0-beta` schema 提交 `6fb6baaf`。该 beta 正文未读 |

S2 参数表第 426 行没有给 `gravityPower` 写下界。A3 第 1139 行把它限制为不小于 0。这是字段约束差异，不是积分式差异。

`spring_bone1` 目录在同一 commit 下还有这些 blob。本轮没有读它们的正文，因此没有行号索引：

| 文件 | blob | 字节 |
| --- | --- | --- |
| `__init__.py` | `3822ea345bcc9fb559a3c14d1cb308e3cd075266` | 51 |
| `menu.py` | `48d2d08755ada7db38453299a537af05ab9db097` | 8595 |
| `migration.py` | `1d714ba7866b4c19994d7fc39e751284720f07ba` | 2795 |
| `ops.py` | `544c9972c89fd4fbd36983c88d2c5b42d85888a5` | 64806 |
| `panel.py` | `828d144613e5dad843f59122e136e2ccfda9a052` | 21723 |
| `ui_list.py` | `aa70b2f8e0f159c82d26bc79a3723485cedfedcd` | 11878 |

### 9.3 UE 符号

U2，272 行：

| 行 | 符号 |
| --- | --- |
| 1 | `Copyright Epic Games, Inc. All Rights Reserved.` |
| 16–39 | 构造。默认值第 17–20 行 |
| 41–47 | `Initialize_AnyThread`。`RemainingTime = 0` |
| 55–64 | `UpdateInternal`。累加 `GetDeltaTime()`，固定步第 63 行 |
| 79–93 | `CopyToVectorByFlags` |
| 95–228 | `EvaluateSkeletalControl_AnyThread` |
| 115 | `TargetPos`，世界空间 |
| 128–130 | `BoneLocation += OwnerVelocity * FixedTimeStep` |
| 133–137 | 误差超过 `ErrorResetThresh` 时重置 |
| 140–145 | `Error`、`DampingForce`、`SpringForce`、`Acceleration` |
| 149–158 | 阻尼大于 `1/dt` 时的速度缩放 |
| 160–165 | 速度模长夹紧 |
| 167–170 | 位置积分 |
| 172–173 | 轴过滤 |
| 177–186 | `MaxDisplacement` 球投影 |
| 189 | 用投影后位移重写速度 |
| 196–204 | 世界位置变回组件空间 |
| 206–221 | 可选旋转。混合空间的减式在第 212–213 行 |
| 231–234 | `IsValidToEvaluate` |
| 242–271 | `PreUpdate`。速度赋值第 251–266 行 |

U3：`SpringBone` 第 26 行，`MaxDisplacement` 第 30 行，`SpringStiffness` 第 34 行，`SpringDamping` 第 38 行，`ErrorResetThresh` 第 42 行，`OwnerVelocity` 注释第 50 行，平移开关第 76–86 行，旋转开关第 88–98 行。

U1：版本宏第 58–60 行，版权字符串第 77 行。

### 9.4 公式对照的行

| 式 | 规格 | 插件 | UE |
| --- | --- | --- | --- |
| 惯性三项 | S2 496–500 | A1 706–726 | 无对应式。U2 140–145 是 `a = kx - cv` |
| 骨长 | S2 503 | A1 729–737 | 无骨长投影。U2 177–186 是误差球 |
| 外球距离 | S2 537 | A1 172 | 无 |
| 外胶囊距离 | S2 568 | A1 212 | 无 |
| 内部球距离 | S4 413 | A1 227 | 无 |
| 内部胶囊距离 | S4 446 | A1 267 | 无 |
| 平面距离 | S4 464 | A1 278 | 无 |
| 平面法线 | S4 460 | A1 408–410 | 无 |
| 限制时机 | S3 154–155 | A1 惯性后与每次推开后 | 无 |
| 限制轴旋转 | S3 431–437 | A3 1093–1098 | 无 |
| 锥 | S3 459–476 | A1 48–68 | 无 |
| 铰 | S3 488–509 | A1 70–87 | 无 |
| 球限制 | S3 517–551 | A1 89–111 | 无 |
| 60 Hz 步 | 规格未规定 | A1 855–875 | 无 |
| 120 Hz 步 | 无 | 无 | U2 62–63、126 |
| 半隐式欧拉 | 无 | 无 | U2 149–170、189 |
| center 定义 | S2 195–207、590–594 | A1 543–553、576–582、699–703 | 无 |

/**
 * 管理员账号管理接口。
 *
 * 对应后端 `apps/accounts/urls_admin.py`（挂在 `/api/admins/` 下）：
 *
 * | 方法   | 路径 | 说明 |
 * | --- | --- | --- |
 * | GET    | `admins/` | 列表：关键字 / 角色 / 状态过滤 + 排序 + 分页 |
 * | POST   | `admins/` | 新建（超级管理员专属） |
 * | GET    | `admins/overview/` | 概览：总数 / 启用 / 停用 / 超级管理员数 |
 * | GET    | `admins/<id>/` | 详情 |
 * | PATCH  | `admins/<id>/` | 改资料与角色（账号名不可改） |
 * | DELETE | `admins/<id>/` | 删除 |
 * | POST   | `admins/<id>/status/` | 启用 / 停用 |
 * | POST   | `admins/<id>/password/` | 重置他人口令（超级管理员） |
 * | POST   | `admins/me/password/` | 改自己的口令（任何登录管理员） |
 *
 * 除"改自己的口令"外，这些接口都只对超级管理员开放（后端 `IsSuperAdmin`）：
 * 管理员账号是**权限的源头**，能改管理员的人等于能改所有人的权限。
 */

import { del, get, patch, post } from './client'
import type {
  AdminCreatePayload,
  AdminDeleteResult,
  AdminPasswordPayload,
  AdminPasswordResult,
  AdminRoleFilter,
  AdminStatusFilter,
  AdminStatusPayload,
  AdminUpdatePayload,
  AdminUser,
  AdminsOverview,
  PageResult,
  SelfPasswordPayload,
} from './types'

/** 列表查询参数（全部可选，后端有默认值）。 */
export interface AdminListQuery {
  /** 账号 / 昵称 / 邮箱（子串匹配，大小写不敏感）。 */
  keyword?: string
  /** 角色过滤，默认 `all`。 */
  role?: AdminRoleFilter
  /** 状态过滤，默认 `all`。 */
  status?: AdminStatusFilter
  /** 排序键，取值见后端 `ADMIN_ORDERING_CHOICES`（默认 `-created_at`）。 */
  ordering?: string
  page?: number
  page_size?: number
}

/** 排序候选（与后端 `serializers_admin.ADMIN_ORDERING_CHOICES` 对齐）。 */
export const ADMIN_ORDERING_OPTIONS: { value: string; label: string }[] = [
  { value: '-created_at', label: '创建时间从新到旧' },
  { value: 'created_at', label: '创建时间从旧到新' },
  { value: 'username', label: '账号名' },
  { value: '-last_login', label: '最后登录从新到旧' },
  { value: 'role', label: '角色' },
]

/** 角色候选（下拉框用；展示文案与后端 `role_display` 一致）。 */
export const ADMIN_ROLE_OPTIONS: { value: AdminUser['role']; label: string }[] = [
  { value: 'operator', label: '运营' },
  { value: 'admin', label: '管理员' },
  { value: 'super_admin', label: '超级管理员' },
]

/** 管理员列表。 */
export function listAdmins(query: AdminListQuery = {}): Promise<PageResult<AdminUser>> {
  return get<PageResult<AdminUser>>('admins/', { params: query })
}

/** 概览数字。 */
export function getAdminsOverview(): Promise<AdminsOverview> {
  return get<AdminsOverview>('admins/overview/')
}

/** 管理员详情。 */
export function getAdmin(adminId: number): Promise<AdminUser> {
  return get<AdminUser>(`admins/${adminId}/`)
}

/**
 * 新建管理员。
 *
 * 口令强度由后端按 Django 的口令校验器判定（长度 ≥ 8、非常见、非纯数字、
 * 不能与账号太像），前端只做"必填 + 长度"这类即时提示。
 */
export function createAdmin(payload: AdminCreatePayload): Promise<AdminUser> {
  return post<AdminUser>('admins/', payload)
}

/** 改资料与角色（只传要改的字段）。 */
export function updateAdmin(adminId: number, payload: AdminUpdatePayload): Promise<AdminUser> {
  return patch<AdminUser>(`admins/${adminId}/`, payload)
}

/** 启用 / 停用。停用后该账号立刻登不进来。 */
export function setAdminStatus(
  adminId: number,
  payload: AdminStatusPayload,
): Promise<AdminUser> {
  return post<AdminUser>(`admins/${adminId}/status/`, payload)
}

/** 超级管理员重置他人口令（会让目标账号已登录的设备需要重新登录）。 */
export function resetAdminPassword(
  adminId: number,
  payload: AdminPasswordPayload,
): Promise<AdminPasswordResult> {
  return post<AdminPasswordResult>(`admins/${adminId}/password/`, payload)
}

/** 删除管理员（物理删除；只想禁用请用 `setAdminStatus`）。 */
export function deleteAdmin(adminId: number): Promise<AdminDeleteResult> {
  return del<AdminDeleteResult>(`admins/${adminId}/`)
}

/** 本人改口令（任何登录管理员都能用，必须带原口令）。 */
export function changeMyPassword(payload: SelfPasswordPayload): Promise<AdminPasswordResult> {
  return post<AdminPasswordResult>('admins/me/password/', payload)
}

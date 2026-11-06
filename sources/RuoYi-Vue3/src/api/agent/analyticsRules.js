import request from '@/utils/request'

// 查询约束由若依后端管理，使用 /dev-api 代理及若依登录令牌。
export function listAnalyticsRules(query) {
  return request({
    url: '/agent/analytics/rules',
    method: 'get',
    params: query
  })
}

export function addAnalyticsRule(data) {
  return request({
    url: '/agent/analytics/rules',
    method: 'post',
    data
  })
}

export function updateAnalyticsRule(data) {
  return request({
    url: '/agent/analytics/rules',
    method: 'put',
    data
  })
}

export function deleteAnalyticsRules(ids) {
  return request({
    url: '/agent/analytics/rules/' + ids.join(','),
    method: 'delete'
  })
}

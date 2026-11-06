package com.ruoyi.web.controller.agent;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.ruoyi.common.annotation.Log;
import com.ruoyi.common.constant.HttpStatus;
import com.ruoyi.common.core.controller.BaseController;
import com.ruoyi.common.core.domain.AjaxResult;
import com.ruoyi.common.enums.BusinessType;
import com.ruoyi.common.exception.ServiceException;
import com.ruoyi.common.utils.SecurityUtils;
import com.ruoyi.system.domain.AgentQueryBlockRule;
import com.ruoyi.system.service.IAgentQueryBlockRuleService;

/**
 * 仅超级管理员可管理和读取的数据分析查询约束规则。
 */
@RestController
@RequestMapping("/agent/analytics/rules")
public class AgentQueryBlockRuleController extends BaseController
{
    @Autowired
    private IAgentQueryBlockRuleService ruleService;

    @GetMapping
    public AjaxResult list(@RequestParam(required = false) String databaseName,
            @RequestParam(required = false) String tableName)
    {
        checkAdmin();
        if (databaseName != null && !databaseName.isEmpty())
        {
            validateName(databaseName, "数据库名");
        }
        if (tableName != null && !tableName.isEmpty())
        {
            validateName(tableName, "表名");
        }
        AgentQueryBlockRule filter = new AgentQueryBlockRule();
        filter.setDatabaseName(databaseName);
        filter.setTableName(tableName);
        return AjaxResult.success(ruleService.selectRuleList(filter));
    }

    @Log(title = "查询约束", businessType = BusinessType.INSERT)
    @PostMapping
    public AjaxResult add(@RequestBody AgentQueryBlockRule rule)
    {
        checkAdmin();
        validateRule(rule);
        rule.setCreateBy(getUsername());
        return toAjax(ruleService.insertRule(rule));
    }

    @Log(title = "查询约束", businessType = BusinessType.UPDATE)
    @PutMapping
    public AjaxResult edit(@RequestBody AgentQueryBlockRule rule)
    {
        checkAdmin();
        validateId(rule.getId());
        validateRule(rule);
        rule.setUpdateBy(getUsername());
        return toAjax(ruleService.updateRule(rule));
    }

    @Log(title = "查询约束", businessType = BusinessType.DELETE)
    @DeleteMapping("/{ids}")
    public AjaxResult remove(@PathVariable Long[] ids)
    {
        checkAdmin();
        if (ids.length == 0)
        {
            throw new ServiceException("请选择要删除的查询约束规则", HttpStatus.BAD_REQUEST);
        }
        for (Long id : ids)
        {
            validateId(id);
        }
        return toAjax(ruleService.deleteRuleByIds(ids));
    }

    private void checkAdmin()
    {
        if (!SecurityUtils.isAdmin(getUserId()))
        {
            throw new ServiceException("仅超级管理员可访问查询约束规则", HttpStatus.FORBIDDEN);
        }
    }

    private void validateRule(AgentQueryBlockRule rule)
    {
        validateName(rule.getDatabaseName(), "数据库名");
        validateName(rule.getTableName(), "表名");
        validateName(rule.getColumnName(), "字段名");
        if ("*".equals(rule.getDatabaseName()))
        {
            throw new ServiceException("数据库名不能使用通配符 *", HttpStatus.BAD_REQUEST);
        }
        if ("*".equals(rule.getTableName()) && !"*".equals(rule.getColumnName()))
        {
            throw new ServiceException("约束整个数据库时，表名和字段名必须同时为 *", HttpStatus.BAD_REQUEST);
        }
        if (rule.getRemark() != null && rule.getRemark().length() > 200)
        {
            throw new ServiceException("备注不能超过200个字符", HttpStatus.BAD_REQUEST);
        }
    }

    private void validateName(String name, String label)
    {
        if (name == null || name.isEmpty())
        {
            throw new ServiceException(label + "不能为空", HttpStatus.BAD_REQUEST);
        }
        if (name.length() > 64 || name.indexOf('\0') >= 0)
        {
            throw new ServiceException(label + "不能超过64个字符或包含NUL字符", HttpStatus.BAD_REQUEST);
        }
    }

    private void validateId(Long id)
    {
        if (id == null || id <= 0)
        {
            throw new ServiceException("查询约束规则ID必须为正整数", HttpStatus.BAD_REQUEST);
        }
    }
}

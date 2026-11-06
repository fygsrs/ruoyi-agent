package com.ruoyi.system.domain;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.ruoyi.common.core.domain.BaseEntity;

/**
 * 数据分析查询约束规则。
 */
@JsonIgnoreProperties(value = { "createBy", "createTime", "updateBy", "updateTime", "params" }, allowGetters = true)
public class AgentQueryBlockRule extends BaseEntity
{
    private static final long serialVersionUID = 1L;

    private Long id;

    private String databaseName;

    private String tableName;

    private String columnName;

    public Long getId()
    {
        return id;
    }

    public void setId(Long id)
    {
        this.id = id;
    }

    public String getDatabaseName()
    {
        return databaseName;
    }

    public void setDatabaseName(String databaseName)
    {
        this.databaseName = databaseName;
    }

    public String getTableName()
    {
        return tableName;
    }

    public void setTableName(String tableName)
    {
        this.tableName = tableName;
    }

    public String getColumnName()
    {
        return columnName;
    }

    public void setColumnName(String columnName)
    {
        this.columnName = columnName;
    }
}

# backend/app/db/base.py
# 作用：定义所有 SQLAlchemy 模型的"基类"
#
# 什么是基类？
# SQLAlchemy 的 ORM 要求每个模型（数据库表）都继承同一个 Base 类。
# 这个 Base 类记录了所有模型的信息，建表时 SQLAlchemy 会扫描它的子类来知道有哪些表。

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    所有数据库模型的基类。

    为什么继承 DeclarativeBase：
    - SQLAlchemy 2.0 推荐的新写法（老版本是 declarative_base()）
    - 继承它的类会自动被识别为数据库表定义
    - 所有表的元数据（metadata）都汇聚在这个 Base 上
    """
    pass

import pymysql

pymysql.version_info = (1, 4, 6, "final", 0)  # Tricks Django into thinking it's mysqlclient
pymysql.install_as_MySQLdb()
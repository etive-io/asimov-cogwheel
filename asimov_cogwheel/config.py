import yaml

def parse_config(filename):
    """
    Parse a yaml-formatted configuration file.

    Parameters
    ----------

    filename: str
       The path to the configuration file.

    """

    with open(filename, "r") as yaml_file:
        data = yaml.safe_load(yaml_file)

    return data

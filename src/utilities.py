
def strip_colors(val):
  color_chars = [
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f', 'A', 'B', 'C', 'D', 'E', 'F']

  while True:
    val_new = val
    code_start = val.find('$')
    if code_start < 0:
      return val
    #
    
    if code_start + 1 == len(val):
      return val[0:-1]
    #
    
    if val[code_start+1] in color_chars:
      if len(val) >= code_start + 4:
        val_new = val[0:code_start] + val[code_start+4:]
      else:
        val_new = val[0:code_start]
      #
    else:
      if len(val) >= code_start + 2:
        val_new = val[0:code_start] + val[code_start+2:]
      else:
        val_new = val[0:code_start]
      #
    #
    if val_new == val:
      return val_new
    #
    val = val_new
  #
#






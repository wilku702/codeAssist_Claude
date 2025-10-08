# Assignment: Word Search
# Given an n by n grid of letters, and a list of words, find the location in the grid where the word can be found. A word matches a straight, contiguous line of letters in the grid. 
# The match could either be done horizontally (left or right) or vertically (up or down) or along any diagonal either right to left or from left to right.
# Input: The input will be in a file word_grid.in. Do not hard code the name of the file in your program. You will read the file from stdin. Here is the format of the input file. Assume that 
# the format is correct; that is you do not have to do any error checking.
# * First line will have one integer - n, the number of lines in the grid and the number of characters in each line.
# * There will be a single blank line.
# * There will be n lines, where each line will have n characters, all in upper case, separated by a space.
# * There will be a single blank line.
# * There will be a single integer k, denoting the number of words that follow.
# * There will be k lines. Each line will contain a single word in all uppercase.

# Output: There will be k lines in your output. Each line will have the word that you are to search, followed by a colon, followed by a single space and then the tuple giving the row and column where you found the word. In the tuple you
# will have two integers (i, j). The number i gives the row and the number j the column of the first letter of the word that you were required to find. Rows and columns are numbered conventionally, i.e. the first row is 1 and the first column is 1. 
# If you do not find a word in the grid then the values for i and j will be 0 and 0. Use the full power of the built-in functions associated with strings and lists. This is the output for the given input file.


import sys

# Input: None
# Output: function returns a 2-D list that is the grid of letters and
#         1-D list of words to search
def read_input():
    lines = [ln.strip() for ln in sys.stdin.read().splitlines()]
    # remove blank lines
    nonblank = [ln for ln in lines if ln != ""]

    idx = 0
    n = int(nonblank[idx]); idx += 1

    grid = []
    for _ in range(n):
        # each line has n uppercase chars separated by spaces
        row = nonblank[idx].split()
        grid.append(row)
        idx += 1

    k = int(nonblank[idx]); idx += 1

    words = []
    for _ in range(k):
        words.append(nonblank[idx].strip())
        idx += 1

    return grid, words

# Input: a 2-D list representing the grid of letters and a single
#        string representing the word to search
# Output: returns a tuple (i, j) containing the row number and the
#         column number of the first letter of the word that you are searching 
#         or (0, 0) if the word does not exist in the grid
def find_word(grid, word):
    n = len(grid)
    wlen = len(word)

    def in_bounds(r, c):
        return 0 <= r < n and 0 <= c < n

    directions = [
        (0, 1),    # right
        (0, -1),   # left
        (1, 0),    # down
        (-1, 0),   # up
        (1, 1),    # down-right
        (-1, -1),  # up-left
    ]

    for r in range(n - 1):        
        for c in range(n - 1):     
            if grid[r][c] != word[0]:
                continue
            for dr, dc in directions:
                rr, cc = r, c
                matched = True
                for k in range(wlen):
                    if not in_bounds(rr, cc) or grid[rr][cc] != word[k]:
                        matched = False
                        break
                    rr += dr
                    cc += dc
                if matched:
                    # Convert to 1-based indexing for output
                    return (r + 1, c + 1)
    return (0, 0)

def main():
    # read the input file from stdin
    word_grid, word_list = read_input()

    # find each word and print its location
    for word in word_list:
        location = find_word(word_grid, word)
        print(f"{word}: {location}")

if __name__ == "__main__":
    main()